"""Simulated print server and retention policy."""

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from printing import services
from printing.models import Document, Printer, PrintJob, PrintRequest

from .base import ChapifyTestCase


class PrintJobLifecycleTests(ChapifyTestCase):
    def setUp(self):
        self.user = self.make_user()
        self.printer = Printer.objects.create(printer_name="Test Printer", location="Lab")
        self.print_request = self.make_paid_request(self.user)
        self.job = PrintJob.objects.get(print_request=self.print_request)

    def test_paid_request_is_queued_on_available_printer(self):
        self.assertEqual(self.job.job_status, PrintJob.STATUS_QUEUED)
        self.assertIsNotNone(self.job.printer)

    def test_successful_print_completes_request_and_deletes_file(self):
        job = services.process_next_print_job()

        self.assertEqual(job.job_status, PrintJob.STATUS_COMPLETED)
        self.assertIsNotNone(job.started_at)
        self.assertIsNotNone(job.completed_at)
        self.print_request.refresh_from_db()
        self.assertEqual(self.print_request.status, PrintRequest.STATUS_COMPLETED)
        self.assertFalse(self.print_request.document.has_file())
        job.printer.refresh_from_db()
        self.assertEqual(job.printer.printer_status, Printer.STATUS_AVAILABLE)

    def test_failed_print_marks_request_failed(self):
        job = services.process_next_print_job(force_failure=True)

        self.assertEqual(job.job_status, PrintJob.STATUS_FAILED)
        self.assertEqual(job.failure_reason, "Simulated printer error.")
        self.print_request.refresh_from_db()
        self.assertEqual(self.print_request.status, PrintRequest.STATUS_FAILED)
        # Kept so that an administrator can retry; removed by the retention policy later.
        self.assertTrue(self.print_request.document.has_file())

    def test_missing_file_fails_the_job(self):
        self.print_request.document.delete_file_from_storage()
        job = services.process_next_print_job()
        self.assertEqual(job.job_status, PrintJob.STATUS_FAILED)
        self.assertEqual(job.failure_reason, "Document file is missing.")

    def test_no_available_printer_leaves_job_queued(self):
        Printer.objects.update(printer_status=Printer.STATUS_OFFLINE)

        self.assertIsNone(services.process_next_print_job())
        self.job.refresh_from_db()
        self.assertEqual(self.job.job_status, PrintJob.STATUS_QUEUED)

    def test_job_cannot_be_finished_twice(self):
        job = services.process_next_print_job()
        with self.assertRaises(services.WorkflowError):
            services.finish_print_job(job, True)

    def test_simulator_command_processes_queue(self):
        out = StringIO()
        call_command("run_print_simulator", "--once", "--seconds-per-page", "0", stdout=out)
        self.assertIn("Processed 1 job(s).", out.getvalue())
        self.job.refresh_from_db()
        self.assertEqual(self.job.job_status, PrintJob.STATUS_COMPLETED)

    def test_admin_dashboard_button_processes_next_job(self):
        self.make_admin()
        self.client.login(username="admin", password="Str0ng-test-pass!")

        response = self.client.post(reverse("admin_process_print_job"), {"simulate_failure": "1"})
        self.assertRedirects(response, reverse("admin_dashboard"))
        self.job.refresh_from_db()
        self.assertEqual(self.job.job_status, PrintJob.STATUS_FAILED)


class RetentionTests(ChapifyTestCase):
    def setUp(self):
        self.user = self.make_user()
        self.old = timezone.now() - timedelta(hours=48)

    def test_abandoned_upload_is_deleted(self):
        document = self.make_document(self.user)
        Document.objects.filter(pk=document.pk).update(upload_time=self.old)

        summary = services.cleanup_documents(older_than_hours=24)
        self.assertEqual(summary["orphan_files"], 1)
        document.refresh_from_db()
        self.assertFalse(document.has_file())

    def test_unpaid_request_expires(self):
        print_request = self.make_request(self.user)
        PrintRequest.objects.filter(pk=print_request.pk).update(updated_at=self.old)

        out = StringIO()
        call_command("cleanup_documents", "--hours", "24", stdout=out)
        print_request.refresh_from_db()
        self.assertEqual(print_request.status, PrintRequest.STATUS_CANCELLED)
        self.assertFalse(print_request.document.has_file())
        self.assertIn("Expired unpaid requests: 1", out.getvalue())

    def test_recent_and_paid_requests_are_untouched(self):
        Printer.objects.create(printer_name="P", location="L")
        recent = self.make_request(self.user)
        paid = self.make_paid_request(self.user)
        PrintRequest.objects.filter(pk=paid.pk).update(updated_at=self.old)

        services.cleanup_documents(older_than_hours=24)
        recent.refresh_from_db()
        paid.refresh_from_db()
        self.assertEqual(recent.status, PrintRequest.STATUS_AWAITING_PAYMENT)
        self.assertTrue(recent.document.has_file())
        self.assertEqual(paid.status, PrintRequest.STATUS_PAYMENT_CONFIRMED)
        self.assertTrue(paid.document.has_file())  # still needed for printing

    def test_failed_job_file_is_removed_after_retention_period(self):
        Printer.objects.create(printer_name="P", location="L")
        failed = self.make_paid_request(self.user)
        services.process_next_print_job(force_failure=True)

        services.cleanup_documents(older_than_hours=24)
        failed.refresh_from_db()
        self.assertTrue(failed.document.has_file())  # still within the retry window

        PrintRequest.objects.filter(pk=failed.pk).update(updated_at=self.old)
        summary = services.cleanup_documents(older_than_hours=24)
        self.assertEqual(summary["terminal_files"], 1)
        self.assertFalse(failed.document.has_file())

    def test_dry_run_changes_nothing(self):
        print_request = self.make_request(self.user)
        PrintRequest.objects.filter(pk=print_request.pk).update(updated_at=self.old)

        summary = services.cleanup_documents(older_than_hours=24, dry_run=True)
        self.assertEqual(summary["expired_requests"], 1)
        print_request.refresh_from_db()
        self.assertEqual(print_request.status, PrintRequest.STATUS_AWAITING_PAYMENT)
