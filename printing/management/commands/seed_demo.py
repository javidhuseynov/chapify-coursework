"""Fill an (empty or existing) database with demonstration data.

Creates one administrator, two students, two printers and print requests in
every important state, using the same service functions as the real
application (including signed gateway notifications), so the audit log and
the data are realistic.

    python manage.py seed_demo
    python manage.py seed_demo --password MyDemoPass123
"""

import io
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from pypdf import PdfWriter

from mockgateway import signing
from printing import services
from printing.models import Printer, Profile
from printing.validators import inspect_uploaded_document

DEMO_USERNAMES = ("demo_admin", "demo_student", "demo_student2")


def make_pdf(name, pages):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="application/pdf")


class Command(BaseCommand):
    help = "Create demonstration users, printers and print requests in all workflow states."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            default=None,
            help="Password for all demo accounts (default: a random one, printed at the end).",
        )

    def handle(self, *args, **options):
        User = get_user_model()

        if User.objects.filter(username__in=DEMO_USERNAMES).exists():
            raise CommandError(
                "Demo accounts already exist. Delete demo_admin, demo_student and demo_student2 "
                "in the Django admin first if you want to recreate the demo data."
            )

        password = options["password"] or secrets.token_urlsafe(9)

        admin = User.objects.create_superuser("demo_admin", "demo_admin@example.com", password)
        student = User.objects.create_user("demo_student", "demo_student@example.com", password)
        student2 = User.objects.create_user("demo_student2", "demo_student2@example.com", password)
        Profile.objects.filter(user=admin).update(role=Profile.ROLE_ADMIN)

        printer, _ = Printer.objects.get_or_create(
            printer_name="Library Printer 1",
            defaults={"location": "Library / Study Center"},
        )
        Printer.objects.filter(pk=printer.pk).update(printer_status=Printer.STATUS_AVAILABLE)
        Printer.objects.get_or_create(
            printer_name="Faculty Printer 2",
            defaults={"location": "Faculty building, room 101", "printer_status": Printer.STATUS_OFFLINE},
        )

        def new_request(user, name, pages, **settings_overrides):
            uploaded = make_pdf(name, pages)
            page_count = inspect_uploaded_document(uploaded)
            document = services.store_uploaded_document(user, uploaded, page_count=page_count)
            options_ = {"copies": 1, "color_mode": "BW", "paper_format": "A4", "duplex_mode": "ONE_SIDED"}
            options_.update(settings_overrides)
            return services.create_print_request(user, document, services.PrintOptions(**options_))

        def gateway(print_request, user, status):
            payment = services.initiate_payment(print_request, user)
            data = {
                "reference": str(payment.reference),
                "amount": str(payment.amount),
                "currency": payment.currency,
                "status": status,
                "gateway_transaction_id": f"MOCK-DEMO{payment.pk:06d}",
            }
            token = signing.sign(data, settings.PAYMENT_GATEWAY_SECRET)
            services.apply_payment_notification(signing.unsign(token, settings.PAYMENT_GATEWAY_SECRET))

        # 1. Completed: paid and printed.
        completed = new_request(student, "lecture_notes.pdf", 12, copies=2)
        gateway(completed, student, "APPROVED")
        services.process_next_print_job(actor=admin)

        # 2. Failed print job (can be retried from the dashboard).
        failed = new_request(student2, "thesis_draft.pdf", 30, color_mode="COLOR")
        gateway(failed, student2, "APPROVED")
        services.process_next_print_job(force_failure=True, actor=admin)

        # 3. Paid and waiting in the print queue.
        queued = new_request(student, "exam_schedule.pdf", 2, paper_format="A3")
        gateway(queued, student, "APPROVED")

        # 4. Payment declined (user can retry).
        declined = new_request(student2, "poster.pdf", 1, color_mode="COLOR", paper_format="A3")
        gateway(declined, student2, "DECLINED")

        # 5. Waiting for payment.
        new_request(student, "reading_list.pdf", 5, duplex_mode="DOUBLE_SIDED")

        # 6. Cancelled by the user.
        cancelled = new_request(student2, "old_version.pdf", 8)
        services.cancel_print_request(cancelled, student2)

        self.stdout.write(self.style.SUCCESS("Demo data created."))
        self.stdout.write("Accounts (all with the same password):")
        for username in DEMO_USERNAMES:
            self.stdout.write(f"  {username}")
        self.stdout.write(f"Password: {password}")
        self.stdout.write(
            "Requests: completed, failed (retry on the dashboard), queued, payment declined, "
            "awaiting payment, cancelled."
        )
