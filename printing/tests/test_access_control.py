"""Authentication, object-level access control (IDOR) and administrator RBAC."""

from django.urls import reverse

from printing.models import Profile

from .base import ChapifyTestCase

USER_PAGES = ["payment", "request_status", "edit_print_request", "cancel_print_request"]
ADMIN_PAGES = ["admin_dashboard", "admin_report", "admin_users", "admin_transactions", "admin_printers"]
ADMIN_API = [
    "/api/admin/summary/",
    "/api/admin/requests/",
    "/api/admin/transactions/",
    "/api/admin/print-jobs/",
    "/api/admin/printers/",
    "/api/admin/audit-logs/",
]


class ObjectOwnershipTests(ChapifyTestCase):
    def setUp(self):
        self.alice = self.make_user("alice")
        self.bob = self.make_user("bob")
        self.alice_request = self.make_request(self.alice)
        self.client.login(username="bob", password="Str0ng-test-pass!")

    def test_other_users_request_pages_return_404(self):
        for name in USER_PAGES:
            url = reverse(name, args=[self.alice_request.id])
            self.assertEqual(self.client.get(url).status_code, 404, name)
            self.assertEqual(self.client.post(url).status_code, 404, name)

    def test_other_users_request_api_returns_404(self):
        rid = self.alice_request.id
        self.assertEqual(self.client.get(f"/api/my/requests/{rid}/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/requests/{rid}/payment/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/requests/{rid}/cancel/").status_code, 404)

    def test_lists_only_show_own_requests(self):
        self.assertNotContains(self.client.get(reverse("request_history")), "lecture_notes.pdf")
        self.assertEqual(self.client.get("/api/my/requests/").json(), [])
        self.assertEqual(self.client.get("/api/my/payments/").json(), [])


class AuthenticationTests(ChapifyTestCase):
    def test_anonymous_user_is_redirected_to_login(self):
        user = self.make_user()
        print_request = self.make_request(user)

        for name in ["upload_document", "request_history"]:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse("login"), response["Location"])

        response = self.client.get(reverse("request_status", args=[print_request.id]))
        self.assertIn(reverse("login"), response["Location"])

    def test_anonymous_api_access_is_refused(self):
        self.assertIn(self.client.get("/api/my/requests/").status_code, (401, 403))

    def test_token_authentication(self):
        self.make_user()
        response = self.client.post(
            "/api/auth/token/", {"username": "alice", "password": "Str0ng-test-pass!"}
        )
        self.assertEqual(response.status_code, 200)
        token = response.json()["token"]

        self.client.logout()
        response = self.client.get("/api/my/requests/", HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(response.status_code, 200)


class AdministratorAccessTests(ChapifyTestCase):
    def setUp(self):
        self.user = self.make_user()
        self.admin = self.make_admin()
        self.make_request(self.user)

    def test_normal_user_is_refused(self):
        self.client.login(username="alice", password="Str0ng-test-pass!")

        for name in ADMIN_PAGES:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
        self.assertEqual(self.client.post(reverse("admin_process_print_job")).status_code, 403)

        for url in ADMIN_API:
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_admin_has_access_to_pages_and_api(self):
        self.client.login(username="admin", password="Str0ng-test-pass!")

        for name in ADMIN_PAGES:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)
        self.assertContains(self.client.get(reverse("admin_dashboard")), "Print Queue")

        for url in ADMIN_API:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_role_comes_from_profile(self):
        # Promote a normal user via the profile only (no Django staff flag).
        Profile.objects.filter(user=self.user).update(role=Profile.ROLE_ADMIN)
        self.client.login(username="alice", password="Str0ng-test-pass!")
        self.assertEqual(self.client.get(reverse("admin_dashboard")).status_code, 200)
        self.assertEqual(self.client.get("/api/admin/summary/").status_code, 200)

        # And demoting removes access again.
        Profile.objects.filter(user=self.user).update(role=Profile.ROLE_USER)
        self.assertEqual(self.client.get(reverse("admin_dashboard")).status_code, 403)
