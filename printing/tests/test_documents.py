"""Upload validation (FR-02) and server-side page counting for pricing (FR-04)."""

from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from printing import services
from printing.models import Document, PrintRequest
from printing.validators import (
    MAX_DOCUMENT_PAGES,
    DocumentValidationError,
    inspect_uploaded_document,
)

from .base import ChapifyTestCase, default_options, pdf_bytes, pdf_file


class InspectDocumentTests(ChapifyTestCase):
    def test_counts_pages_of_a_real_pdf(self):
        self.assertEqual(inspect_uploaded_document(pdf_file(pages=3)), 3)

    def test_file_can_still_be_read_after_inspection(self):
        uploaded = pdf_file(pages=2)
        inspect_uploaded_document(uploaded)
        self.assertEqual(uploaded.read(5), b"%PDF-")

    def assert_rejected(self, uploaded, message_part):
        with self.assertRaises(DocumentValidationError) as caught:
            inspect_uploaded_document(uploaded)
        self.assertIn(message_part, str(caught.exception))

    def test_other_formats_are_rejected(self):
        self.assert_rejected(SimpleUploadedFile("notes.txt", b"hello"), "Only PDF")
        self.assert_rejected(SimpleUploadedFile("essay.docx", b"PK\x03\x04"), "Only PDF")

    def test_renamed_non_pdf_is_rejected(self):
        self.assert_rejected(SimpleUploadedFile("photo.pdf", b"\x89PNG\r\n\x1a\n" + b"0" * 100), "not a valid PDF")

    def test_damaged_pdf_is_rejected(self):
        with self.assertRaises(DocumentValidationError):
            inspect_uploaded_document(SimpleUploadedFile("broken.pdf", b"%PDF-1.7\nthis is not really a pdf"))

    def test_password_protected_pdf_is_rejected(self):
        self.assert_rejected(pdf_file(password="secret"), "Password-protected")

    def test_oversized_file_is_rejected(self):
        self.assert_rejected(SimpleUploadedFile("big.pdf", b"%PDF-1.4\n" + b"0" * (5 * 1024 * 1024)), "5 MB")

    def test_too_many_pages_is_rejected(self):
        self.assert_rejected(pdf_file(pages=MAX_DOCUMENT_PAGES + 1), "maximum")


class TrustedPricingTests(ChapifyTestCase):
    def setUp(self):
        self.user = self.make_user()
        self.client.login(username="alice", password="Str0ng-test-pass!")

    def test_web_upload_stores_counted_pages_and_ignores_posted_value(self):
        self.client.post(reverse("upload_document"), {"file": pdf_file(pages=3)})
        document = Document.objects.get(user=self.user)
        self.assertEqual(document.page_count, 3)

        page = self.client.get(reverse("print_settings", args=[document.id]))
        self.assertContains(page, "3 pages")

        # A manipulated form claiming 1 page does not change the price.
        self.client.post(
            reverse("print_settings", args=[document.id]),
            {"document_pages": 1, "copies": 1, "color_mode": "BW", "paper_format": "A4", "duplex_mode": "ONE_SIDED"},
        )
        print_request = PrintRequest.objects.get(document=document)
        self.assertEqual(print_request.document_pages, 3)
        self.assertEqual(print_request.total_price, Decimal("0.30"))

    def test_web_upload_rejects_invalid_file(self):
        response = self.client.post(
            reverse("upload_document"),
            {"file": SimpleUploadedFile("fake.pdf", b"just text")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not a valid PDF")
        self.assertFalse(Document.objects.exists())

    def test_api_ignores_client_page_count(self):
        response = self.client.post(
            "/api/requests/create/",
            {
                "file": pdf_file(pages=4),
                "document_pages": 1,
                "copies": 1,
                "color_mode": "BW",
                "paper_format": "A4",
                "duplex_mode": "ONE_SIDED",
            },
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()["print_request"]
        self.assertEqual(body["document_pages"], 4)
        self.assertEqual(body["total_price"], "0.40")
        self.assertEqual(body["document"]["page_count"], 4)

    def test_api_rejects_invalid_file(self):
        response = self.client.post(
            "/api/requests/create/",
            {
                "file": SimpleUploadedFile("fake.pdf", b"just text"),
                "copies": 1,
                "color_mode": "BW",
                "paper_format": "A4",
                "duplex_mode": "ONE_SIDED",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("file", response.json())

    def test_document_without_page_count_cannot_be_used(self):
        # Documents uploaded before page counting existed.
        document = self.make_document(self.user)
        Document.objects.filter(pk=document.pk).update(page_count=None)
        document.refresh_from_db()

        with self.assertRaises(services.WorkflowError):
            services.create_print_request(self.user, document, default_options())

    def test_editing_keeps_the_counted_pages(self):
        print_request = self.make_request(self.user)
        services.update_print_request(print_request, default_options(copies=1, color_mode="BW"), self.user)
        print_request.refresh_from_db()
        self.assertEqual(print_request.document_pages, 10)
        self.assertEqual(print_request.total_price, Decimal("1.00"))

    def test_pdf_helper_produces_requested_pages(self):
        from io import BytesIO

        from pypdf import PdfReader

        self.assertEqual(len(PdfReader(BytesIO(pdf_bytes(7))).pages), 7)
