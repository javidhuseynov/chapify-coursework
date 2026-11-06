"""Polished interface: role-based entry, navigation, new pages, timeline, pagination."""

from django.urls import reverse

from printing import services
from printing.models import AuditLog, PrintRequest

from .base import PASSWORD, ChapifyTestCase


class EntryAndRoleRoutingTests(ChapifyTestCase):
    def test_visitors_only_see_login(self):
        response = self.client.get(reverse("home"))
        self.assertRedirects(response, reverse("login"))
        page = self.client.get(reverse("login"))
        self.assertContains(page, "Log in")
        self.assertContains(page, reverse("register"))
        self.assertNotContains(page, reverse("upload_document"))

    def test_user_lands_on_print_home(self):
        self.make_user()
        response = self.client.post(reverse("login"), {"username": "alice", "password": PASSWORD}, follow=True)
        self.assertEqual(response.request["PATH_INFO"], reverse("home"))
        self.assertContains(response, "Print a document")

    def test_admin_lands_on_operations_overview(self):
        self.make_admin()
        response = self.client.post(reverse("login"), {"username": "admin", "password": PASSWORD}, follow=True)
        self.assertEqual(response.request["PATH_INFO"], reverse("admin_dashboard"))
        self.assertContains(response, "Print queue")

    def test_logged_in_users_skip_login_and_register(self):
        self.client.force_login(self.make_user())
        self.assertRedirects(self.client.get(reverse("login")), reverse("home"))
        self.assertRedirects(self.client.get(reverse("register")), reverse("home"))


class RoleBasedNavigationTests(ChapifyTestCase):
    def test_user_navigation_has_no_admin_links(self):
        self.client.force_login(self.make_user())
        page = self.client.get(reverse("home"))
        self.assertContains(page, reverse("request_history"))
        for name in ("admin_dashboard", "admin_users", "admin_transactions", "admin_audit"):
            self.assertNotContains(page, reverse(name))
        self.assertNotContains(page, "/admin/")

    def test_admin_navigation_has_operations_not_printing(self):
        self.client.force_login(self.make_admin())
        page = self.client.get(reverse("admin_dashboard"))
        for name in ("admin_requests", "admin_users", "admin_transactions", "admin_printers", "admin_audit", "admin_report"):
            self.assertContains(page, reverse(name))
        self.assertNotContains(page, reverse("upload_document"))
        self.assertNotContains(page, reverse("request_history"))
        self.assertContains(page, 'aria-current="page"')


class UserPagesTests(ChapifyTestCase):
    def setUp(self):
        self.user = self.make_user()
        self.client.force_login(self.user)

    def test_home_shows_open_requests(self):
        self.make_request(self.user)
        page = self.client.get(reverse("home"))
        self.assertContains(page, "lecture_notes.pdf")
        self.assertContains(page, "Awaiting payment")

    def test_settings_page_has_price_estimate(self):
        document = self.make_document(self.user, pages=10)
        page = self.client.get(reverse("print_settings", args=[document.id]))
        self.assertContains(page, 'id="pricing-data"')
        self.assertContains(page, "1.00")  # 10 pages, 1 copy, black and white, A4

    def test_copies_are_limited(self):
        document = self.make_document(self.user)
        response = self.client.post(
            reverse("print_settings", args=[document.id]),
            {"copies": 500, "color_mode": "BW", "paper_format": "A4", "duplex_mode": "ONE_SIDED"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PrintRequest.objects.exists())

    def test_request_page_shows_timeline(self):
        paid = self.make_paid_request(self.user)
        page = self.client.get(reverse("request_status", args=[paid.id]))
        self.assertContains(page, "Request created")
        self.assertContains(page, "Payment confirmed")
        self.assertContains(page, "Added to the print queue")

        services.process_next_print_job()
        page = self.client.get(reverse("request_status", args=[paid.id]))
        self.assertContains(page, "Printed")

    def test_history_is_paginated(self):
        for _ in range(17):
            self.make_request(self.user)
        page = self.client.get(reverse("request_history"))
        self.assertContains(page, "Page 1 of 2")
        self.assertContains(self.client.get(reverse("request_history"), {"page": 2}), "Page 2 of 2")

    def test_help_page(self):
        page = self.client.get(reverse("help"))
        self.assertContains(page, "4.00 EUR")  # thesis example
        self.assertContains(page, "0.162")      # A3, black and white, double-sided page price

    def test_change_password(self):
        response = self.client.post(
            reverse("account"),
            {"old_password": PASSWORD, "new_password1": "An0ther-strong-pass", "new_password2": "An0ther-strong-pass"},
        )
        self.assertRedirects(response, reverse("account"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("An0ther-strong-pass"))
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)  # still logged in
        self.assertTrue(AuditLog.objects.filter(description__contains="changed their password").exists())


class AdminPagesTests(ChapifyTestCase):
    def setUp(self):
        self.admin = self.make_admin()
        self.user = self.make_user()
        self.client.force_login(self.admin)

    def test_requests_page_filters(self):
        self.make_request(self.user)
        page = self.client.get(reverse("admin_requests"), {"q": "alice"})
        self.assertContains(page, "lecture_notes.pdf")
        page = self.client.get(reverse("admin_requests"), {"status": "COMPLETED"})
        self.assertContains(page, "No requests found")

    def test_audit_page_filters_by_event(self):
        self.make_request(self.user)
        page = self.client.get(reverse("admin_audit"), {"status": "PRINT_REQUEST_CREATED"})
        self.assertContains(page, "Print request created")
        self.assertNotContains(page, "Document uploaded:")

    def test_report_page(self):
        self.make_paid_request(self.user)
        page = self.client.get(reverse("admin_report"))
        self.assertContains(page, "Payment confirmed")
        self.assertContains(page, "4.00 EUR")


class ErrorPageTests(ChapifyTestCase):
    def test_custom_404(self):
        response = self.client.get("/no-such-page/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Page not found", status_code=404)

    def test_custom_403(self):
        self.client.force_login(self.make_user())
        response = self.client.get(reverse("admin_dashboard"))
        self.assertContains(response, "access to this page", status_code=403)
