"""M6: lockout after repeated failed logins (web form and API token endpoint)."""

from django.test import override_settings
from django.urls import reverse

from printing.models import AuditLog

from .base import PASSWORD, ChapifyTestCase


@override_settings(LOGIN_FAILURE_LIMIT=3, LOGIN_LOCKOUT_SECONDS=600)
class LoginLockoutTests(ChapifyTestCase):
    def setUp(self):
        self.user = self.make_user()

    def attempt(self, password, ip="10.0.0.1"):
        return self.client.post(
            reverse("login"),
            {"username": "alice", "password": password},
            REMOTE_ADDR=ip,
        )

    def test_correct_password_works_before_limit(self):
        self.attempt("wrong")
        self.attempt("wrong")
        response = self.attempt(PASSWORD)
        self.assertEqual(response.status_code, 302)

    def test_lockout_after_limit_even_with_correct_password(self):
        for _ in range(3):
            self.attempt("wrong")

        response = self.attempt(PASSWORD)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Too many failed login attempts")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(
            AuditLog.objects.filter(event_type=AuditLog.EVENT_LOGIN_FAILED, description__contains="refused").exists()
        )

    def test_lockout_is_per_ip_address(self):
        for _ in range(3):
            self.attempt("wrong", ip="10.0.0.1")

        response = self.attempt(PASSWORD, ip="10.0.0.2")
        self.assertEqual(response.status_code, 302)

    def test_success_resets_the_counter(self):
        self.attempt("wrong")
        self.attempt("wrong")
        self.attempt(PASSWORD)
        self.client.logout()

        self.attempt("wrong")
        self.attempt("wrong")
        self.assertEqual(self.attempt(PASSWORD).status_code, 302)

    def test_api_token_endpoint_is_protected(self):
        for _ in range(3):
            self.client.post("/api/auth/token/", {"username": "alice", "password": "wrong"}, REMOTE_ADDR="10.0.0.9")

        response = self.client.post(
            "/api/auth/token/", {"username": "alice", "password": PASSWORD}, REMOTE_ADDR="10.0.0.9"
        )
        self.assertEqual(response.status_code, 429)

        response = self.client.post(
            "/api/auth/token/", {"username": "alice", "password": PASSWORD}, REMOTE_ADDR="10.0.0.10"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("token", response.json())
