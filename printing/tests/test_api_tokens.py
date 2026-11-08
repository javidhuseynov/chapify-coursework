"""Expiring, revocable API tokens and the OpenAPI documentation."""

from datetime import timedelta

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from printing import api_tokens, services
from printing.models import ApiToken, AuditLog, Profile

from .base import PASSWORD, ChapifyTestCase


def auth(raw_token):
    return {"HTTP_AUTHORIZATION": f"Token {raw_token}"}


class TokenIssueTests(ChapifyTestCase):
    def setUp(self):
        self.user = self.make_user()

    def obtain(self, **extra):
        data = {"username": "alice", "password": PASSWORD}
        data.update(extra)
        return self.client.post("/api/auth/token/", data)

    def test_login_returns_token_once_and_stores_only_its_hash(self):
        response = self.obtain(name="Chapify mobile")
        self.assertEqual(response.status_code, 201)
        body = response.json()
        raw_token = body["token"]

        self.assertTrue(raw_token.startswith("chp_"))
        self.assertEqual(body["name"], "Chapify mobile")
        token = ApiToken.objects.get(pk=body["id"])
        self.assertNotEqual(token.key_hash, raw_token)
        self.assertNotIn(raw_token, token.key_hash)
        self.assertEqual(token.key_hash, api_tokens.hash_token(raw_token))
        self.assertTrue(AuditLog.objects.filter(event_type=AuditLog.EVENT_API_TOKEN_CREATED).exists())

    @override_settings(API_TOKEN_TTL_HOURS=48)
    def test_token_expiry_follows_setting(self):
        expires_at = ApiToken.objects.get(pk=self.obtain().json()["id"]).expires_at
        self.assertAlmostEqual(
            (expires_at - timezone.now()).total_seconds(), 48 * 3600, delta=60
        )

    def test_wrong_password_and_blocked_account_get_no_token(self):
        self.assertEqual(self.obtain(password="wrong").status_code, 400)
        services.set_account_status(self.user, Profile.STATUS_BLOCKED, self.make_admin())
        self.assertEqual(self.obtain().status_code, 400)
        self.assertFalse(ApiToken.objects.exists())

    def test_bearer_keyword_is_accepted(self):
        raw_token = self.obtain().json()["token"]
        response = self.client.get("/api/my/requests/", HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        self.assertEqual(response.status_code, 200)

    @override_settings(API_TOKENS_PER_USER=2)
    def test_oldest_tokens_are_revoked_above_the_limit(self):
        first = self.obtain(name="one").json()["token"]
        self.obtain(name="two")
        self.obtain(name="three")

        self.assertEqual(api_tokens.active_tokens(self.user).count(), 2)
        self.assertEqual(self.client.get("/api/my/requests/", **auth(first)).status_code, 401)


class TokenValidityTests(ChapifyTestCase):
    def setUp(self):
        self.user = self.make_user()
        self.token, self.raw_token = api_tokens.issue_token(self.user, "phone")

    def get_requests(self, raw_token=None):
        return self.client.get("/api/my/requests/", **auth(raw_token or self.raw_token))

    def test_valid_token_works_and_records_last_use(self):
        self.assertEqual(self.get_requests().status_code, 200)
        self.token.refresh_from_db()
        self.assertIsNotNone(self.token.last_used_at)

    def test_expired_token_is_refused(self):
        ApiToken.objects.filter(pk=self.token.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        response = self.get_requests()
        self.assertEqual(response.status_code, 401)
        self.assertIn("expired", response.json()["detail"])

    def test_unknown_or_malformed_token_is_refused(self):
        self.assertEqual(self.get_requests("chp_not-a-real-token").status_code, 401)
        response = self.client.get("/api/my/requests/", HTTP_AUTHORIZATION="Token")
        self.assertEqual(response.status_code, 401)

    def test_logout_revokes_only_the_current_token(self):
        other, other_raw = api_tokens.issue_token(self.user, "laptop")

        response = self.client.post("/api/auth/token/revoke/", **auth(self.raw_token))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.get_requests().status_code, 401)
        self.assertEqual(self.get_requests(other_raw).status_code, 200)

    def test_list_and_revoke_own_tokens(self):
        other, other_raw = api_tokens.issue_token(self.user, "laptop")
        listed = self.client.get("/api/auth/tokens/", **auth(self.raw_token)).json()

        self.assertEqual({t["name"] for t in listed}, {"phone", "laptop"})
        self.assertEqual([t["current"] for t in listed if t["name"] == "phone"], [True])
        self.assertNotIn("key_hash", listed[0])

        response = self.client.delete(f"/api/auth/tokens/{other.pk}/", **auth(self.raw_token))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.get_requests(other_raw).status_code, 401)

    def test_cannot_revoke_another_users_token(self):
        bob = self.make_user("bob")
        bob_token, bob_raw = api_tokens.issue_token(bob, "bob phone")

        response = self.client.delete(f"/api/auth/tokens/{bob_token.pk}/", **auth(self.raw_token))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.get_requests(bob_raw).status_code, 200)

    def test_password_change_logs_out_all_apps(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("account"),
            {"old_password": PASSWORD, "new_password1": "An0ther-str0ng-pass", "new_password2": "An0ther-str0ng-pass"},
        )
        self.assertEqual(response.status_code, 302)
        self.client.logout()
        self.assertEqual(self.get_requests().status_code, 401)

    def test_account_page_lists_and_revokes_apps(self):
        self.client.force_login(self.user)
        page = self.client.get(reverse("account")).content.decode()
        self.assertIn("phone", page)
        self.assertIn(self.token.key_prefix, page)
        self.assertNotIn(self.raw_token, page)

        self.client.post(reverse("account_revoke_token", args=[self.token.pk]))
        self.client.logout()
        self.assertEqual(self.get_requests().status_code, 401)

    def test_purge_removes_long_expired_tokens(self):
        ApiToken.objects.filter(pk=self.token.pk).update(expires_at=timezone.now() - timedelta(days=40))
        self.assertEqual(api_tokens.purge_old_tokens(), 1)
        self.assertFalse(ApiToken.objects.exists())


class ApiDocumentationTests(ChapifyTestCase):
    def test_docs_and_schema_require_login(self):
        response = self.client.get(reverse("api_docs"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])
        self.assertIn(self.client.get(reverse("api_schema")).status_code, (401, 403))

    def test_schema_describes_the_api(self):
        self.client.force_login(self.make_user())
        response = self.client.get(reverse("api_schema"), {"format": "json"})
        self.assertEqual(response.status_code, 200)
        schema = response.json()

        self.assertEqual(schema["info"]["title"], "Chapify API")
        self.assertIn("/api/auth/token/", schema["paths"])
        self.assertIn("/api/requests/{request_id}/payment/", schema["paths"])
        self.assertIn("tokenAuth", schema["components"]["securitySchemes"])
        # Nothing in the API lets a client confirm its own payment.
        self.assertFalse([p for p in schema["paths"] if "confirm" in p])

    def test_docs_page_works_under_the_content_security_policy(self):
        self.client.force_login(self.make_user())
        response = self.client.get(reverse("api_docs"))
        self.assertEqual(response.status_code, 200)
        page = response.content.decode()

        self.assertNotIn("<style", page)
        self.assertNotIn("<script>", page)
        self.assertNotIn("cdn.", page)
        self.assertIn("swagger-ui-bundle.js", page)

        script = self.client.get(reverse("api_docs"), {"script": ""})
        self.assertEqual(script.status_code, 200)
        self.assertIn("javascript", script["Content-Type"])
