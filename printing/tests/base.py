import shutil
import tempfile
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from mockgateway import signing
from printing import services
from printing.models import PaymentTransaction

User = get_user_model()
PASSWORD = "Str0ng-test-pass!"


def pdf_file(name="lecture_notes.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4\n% test document\n", content_type="application/pdf")


def default_options(**overrides):
    values = {
        "document_pages": 10,
        "copies": 2,
        "color_mode": "COLOR",
        "paper_format": "A4",
        "duplex_mode": "ONE_SIDED",
    }
    values.update(overrides)
    return services.PrintOptions(**values)


def sign_notification(payment, status="APPROVED", **overrides):
    data = {
        "reference": str(payment.reference),
        "amount": str(payment.amount),
        "currency": payment.currency,
        "status": status,
        "gateway_transaction_id": overrides.pop("gateway_transaction_id", "MOCK-TEST0001"),
    }
    data.update(overrides)
    issued_at = data.pop("issued_at", None)
    return signing.sign(data, settings.PAYMENT_GATEWAY_SECRET, issued_at=issued_at)


def query_param(url, name):
    return parse_qs(urlsplit(url).query)[name][0]


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ChapifyTestCase(TestCase):
    """Base class: isolated temporary folder for uploaded files, helper factories."""

    @classmethod
    def setUpClass(cls):
        cls._media_dir = tempfile.mkdtemp(prefix="chapify-test-media-")
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_dir)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_dir, ignore_errors=True)

    def make_user(self, username="alice"):
        return User.objects.create_user(username=username, email=f"{username}@example.com", password=PASSWORD)

    def make_admin(self, username="admin"):
        return User.objects.create_superuser(username=username, email=f"{username}@example.com", password=PASSWORD)

    def make_document(self, user, name="lecture_notes.pdf"):
        return services.store_uploaded_document(user, pdf_file(name))

    def make_request(self, user, **option_overrides):
        document = self.make_document(user)
        return services.create_print_request(user, document, default_options(**option_overrides))

    def make_paid_request(self, user, **option_overrides):
        print_request = self.make_request(user, **option_overrides)
        payment = services.initiate_payment(print_request, user)
        services.apply_payment_notification(
            signing.unsign(sign_notification(payment), settings.PAYMENT_GATEWAY_SECRET)
        )
        print_request.refresh_from_db()
        return print_request

    def confirmed_payments(self, print_request):
        return PaymentTransaction.objects.filter(
            print_request=print_request,
            payment_status=PaymentTransaction.STATUS_CONFIRMED,
        )
