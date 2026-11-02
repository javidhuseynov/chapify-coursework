"""Print request workflow: creation, document reuse, editing, cancellation, profiles."""

from decimal import Decimal

from django.urls import reverse

from printing import services
from printing.models import AuditLog, PaymentTransaction, PrintRequest, Profile

from .base import ChapifyTestCase, default_options


class ProfileTests(ChapifyTestCase):
    def test_new_user_gets_user_profile(self):
        user = self.make_user()
        self.assertEqual(user.profile.role, Profile.ROLE_USER)

    def test_superuser_gets_admin_profile(self):
        admin = self.make_admin()
        self.assertEqual(admin.profile.role, Profile.ROLE_ADMIN)

    def test_registration_creates_profile(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "newbie",
                "email": "newbie@example.com",
                "password1": "Str0ng-test-pass!",
                "password2": "Str0ng-test-pass!",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Profile.objects.filter(user__username="newbie", role=Profile.ROLE_USER).exists())


class CreateRequestTests(ChapifyTestCase):
    def setUp(self):
        self.user = self.make_user()
        self.client.login(username="alice", password="Str0ng-test-pass!")

    def test_web_upload_and_settings_create_priced_request(self):
        from .base import pdf_file

        response = self.client.post(reverse("upload_document"), {"file": pdf_file()})
        self.assertEqual(response.status_code, 302)
        document = self.user.document_set.get()
        self.assertTrue(document.has_file())
        self.assertEqual(document.temporary_storage_path, document.file.name)

        response = self.client.post(
            reverse("print_settings", args=[document.id]),
            {"document_pages": 10, "copies": 2, "color_mode": "COLOR", "paper_format": "A4", "duplex_mode": "ONE_SIDED"},
        )
        print_request = PrintRequest.objects.get(document=document)
        self.assertRedirects(response, reverse("payment", args=[print_request.id]))
        self.assertEqual(print_request.status, PrintRequest.STATUS_AWAITING_PAYMENT)
        self.assertEqual(print_request.total_price, Decimal("4.00"))
        self.assertTrue(
            AuditLog.objects.filter(event_type=AuditLog.EVENT_PRINT_REQUEST_CREATED, print_request=print_request).exists()
        )

    def test_invalid_extension_is_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        response = self.client.post(
            reverse("upload_document"),
            {"file": SimpleUploadedFile("virus.exe", b"MZ")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.user.document_set.exists())

    def test_document_cannot_be_used_twice(self):
        print_request = self.make_request(self.user)

        with self.assertRaises(services.WorkflowError):
            services.create_print_request(self.user, print_request.document, default_options())

        # The web page refuses too (e.g. browser Back + resubmit) and shows the existing request.
        response = self.client.post(
            reverse("print_settings", args=[print_request.document.id]),
            {"document_pages": 1, "copies": 1, "color_mode": "BW", "paper_format": "A4", "duplex_mode": "ONE_SIDED"},
        )
        self.assertRedirects(response, reverse("request_status", args=[print_request.id]))
        self.assertEqual(PrintRequest.objects.filter(document=print_request.document).count(), 1)

    def test_document_without_file_cannot_be_used(self):
        document = self.make_document(self.user)
        document.delete_file_from_storage()

        with self.assertRaises(services.WorkflowError):
            services.create_print_request(self.user, document, default_options())

    def test_other_users_document_cannot_be_used(self):
        other = self.make_user("bob")
        document = self.make_document(other)

        with self.assertRaises(services.WorkflowError):
            services.create_print_request(self.user, document, default_options())

        response = self.client.get(reverse("print_settings", args=[document.id]))
        self.assertEqual(response.status_code, 404)


class EditAndCancelTests(ChapifyTestCase):
    def setUp(self):
        self.user = self.make_user()
        self.client.login(username="alice", password="Str0ng-test-pass!")
        self.print_request = self.make_request(self.user)

    def test_edit_recalculates_price_and_cancels_open_payment_attempt(self):
        # The posted "document_pages" is ignored: the PDF has 10 pages.
        attempt = services.initiate_payment(self.print_request, self.user)

        response = self.client.post(
            reverse("edit_print_request", args=[self.print_request.id]),
            {"document_pages": 1, "copies": 1, "color_mode": "BW", "paper_format": "A4", "duplex_mode": "ONE_SIDED"},
        )
        self.assertRedirects(response, reverse("payment", args=[self.print_request.id]))

        self.print_request.refresh_from_db()
        attempt.refresh_from_db()
        self.assertEqual(self.print_request.document_pages, 10)
        self.assertEqual(self.print_request.total_price, Decimal("1.00"))
        self.assertEqual(attempt.payment_status, PaymentTransaction.STATUS_CANCELLED)
        self.assertTrue(
            AuditLog.objects.filter(event_type=AuditLog.EVENT_PRINT_REQUEST_UPDATED, print_request=self.print_request).exists()
        )

    def test_edit_refused_after_payment(self):
        paid = self.make_paid_request(self.user)

        with self.assertRaises(services.WorkflowError):
            services.update_print_request(paid, default_options(copies=1), self.user)

        response = self.client.get(reverse("edit_print_request", args=[paid.id]))
        self.assertRedirects(response, reverse("request_status", args=[paid.id]))

    def test_cancel_deletes_file_and_closes_request(self):
        attempt = services.initiate_payment(self.print_request, self.user)

        response = self.client.post(reverse("cancel_print_request", args=[self.print_request.id]))
        self.assertRedirects(response, reverse("request_history"))

        self.print_request.refresh_from_db()
        attempt.refresh_from_db()
        self.assertEqual(self.print_request.status, PrintRequest.STATUS_CANCELLED)
        self.assertEqual(attempt.payment_status, PaymentTransaction.STATUS_CANCELLED)
        self.assertFalse(self.print_request.document.has_file())
        self.assertTrue(
            AuditLog.objects.filter(event_type=AuditLog.EVENT_PRINT_REQUEST_CANCELLED, print_request=self.print_request).exists()
        )

    def test_cancel_twice_is_refused(self):
        services.cancel_print_request(self.print_request, self.user)

        with self.assertRaises(services.WorkflowError):
            services.cancel_print_request(self.print_request, self.user)

    def test_paid_request_cannot_be_cancelled(self):
        paid = self.make_paid_request(self.user)

        with self.assertRaises(services.WorkflowError):
            services.cancel_print_request(paid, self.user)

    def test_pages_render(self):
        for name in ("home", "upload_document", "request_history"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

        for name in ("payment", "request_status", "edit_print_request", "cancel_print_request"):
            response = self.client.get(reverse(name, args=[self.print_request.id]))
            self.assertEqual(response.status_code, 200, name)

        response = self.client.get(reverse("request_history"), {"q": "lecture", "status": "AWAITING_PAYMENT"})
        self.assertContains(response, "lecture_notes.pdf")
