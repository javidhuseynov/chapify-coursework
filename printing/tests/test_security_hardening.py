"""Security checklist additions: headers, request size limit, registration bot protection."""

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from printing.forms import registration_form_token
from printing.models import AuditLog

from .base import ChapifyTestCase, registration_data

User = get_user_model()


class SecurityHeaderTests(ChapifyTestCase):
    def test_pages_send_security_headers(self):
        response = self.client.get(reverse("home"))
        csp = response["Content-Security-Policy"]

        for directive in (
            "default-src 'self'",
            "object-src 'none'",
            "base-uri 'none'",
            "frame-ancestors 'none'",
            "form-action 'self'",
            "style-src 'self' https://cdn.jsdelivr.net",
        ):
            self.assertIn(directive, csp)

        self.assertIn("camera=()", response["Permissions-Policy"])
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Referrer-Policy"], "same-origin")

    def test_templates_use_no_inline_styles_or_scripts(self):
        # Required for the strict CSP (no 'unsafe-inline').
        for name in ("home", "login", "register"):
            content = self.client.get(reverse(name)).content.decode()
            self.assertNotIn("style=", content, name)
            self.assertNotIn("<script", content, name)
            self.assertIn('integrity="sha384-', content, name)

    def test_api_responses_have_headers_too(self):
        response = self.client.post("/api/auth/token/", {"username": "x", "password": "y"})
        self.assertIn("Content-Security-Policy", response)


class RequestSizeLimitTests(ChapifyTestCase):
    def test_oversized_request_is_refused_before_reading(self):
        user = self.make_user()
        self.client.force_login(user)

        response = self.client.post(
            reverse("upload_document"),
            {"file": ""},
            CONTENT_LENGTH=str(50 * 1024 * 1024),
        )
        self.assertEqual(response.status_code, 413)

    def test_normal_upload_is_allowed(self):
        from .base import pdf_file

        user = self.make_user()
        self.client.force_login(user)
        response = self.client.post(reverse("upload_document"), {"file": pdf_file(pages=2)})
        self.assertEqual(response.status_code, 302)


class RegistrationBotProtectionTests(ChapifyTestCase):
    def register(self, **overrides):
        return self.client.post(reverse("register"), registration_data("newbie", **overrides))

    def assert_refused(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Registration could not be completed")
        self.assertFalse(User.objects.filter(username="newbie").exists())
        self.assertTrue(AuditLog.objects.filter(event_type=AuditLog.EVENT_REGISTRATION_REFUSED).exists())

    def test_person_can_register(self):
        response = self.register()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username="newbie").exists())

    def test_filled_honeypot_is_refused(self):
        self.assert_refused(self.register(website="https://spam.example"))

    def test_too_fast_submission_is_refused(self):
        self.assert_refused(self.register(seconds_ago=0))

    def test_missing_or_forged_timestamp_is_refused(self):
        self.assert_refused(self.register(form_started=""))
        self.assert_refused(self.register(form_started="123:forged:signature"))

    def test_expired_form_is_refused(self):
        self.assert_refused(self.register(seconds_ago=2 * 24 * 60 * 60))

    def test_form_contains_hidden_timestamp_and_honeypot(self):
        content = self.client.get(reverse("register")).content.decode()
        self.assertIn('name="form_started"', content)
        self.assertIn('name="website"', content)
        self.assertIn('class="d-none"', content)

    @override_settings(REGISTRATION_LIMIT_PER_IP=2)
    def test_registration_attempts_are_rate_limited_per_ip(self):
        for number in range(2):
            self.client.post(reverse("register"), registration_data(f"user{number}"), REMOTE_ADDR="10.1.1.1")

        response = self.client.post(reverse("register"), registration_data("user9"), REMOTE_ADDR="10.1.1.1")
        self.assertEqual(response.status_code, 429)
        self.assertFalse(User.objects.filter(username="user9").exists())

        response = self.client.post(reverse("register"), registration_data("user8"), REMOTE_ADDR="10.1.1.2")
        self.assertEqual(response.status_code, 302)

    def test_token_helper_round_trip(self):
        self.assertTrue(registration_form_token())
