from io import StringIO

from django.core.management import CommandError, call_command

from printing.models import PrintJob, PrintRequest

from .base import ChapifyTestCase


class SeedDemoTests(ChapifyTestCase):
    def test_creates_requests_in_every_state(self):
        out = StringIO()
        call_command("seed_demo", "--password", "Demo-pass-123", stdout=out)

        statuses = set(PrintRequest.objects.values_list("status", flat=True))
        self.assertTrue(
            {
                PrintRequest.STATUS_COMPLETED,
                PrintRequest.STATUS_FAILED,
                PrintRequest.STATUS_PAYMENT_CONFIRMED,
                PrintRequest.STATUS_PAYMENT_REJECTED,
                PrintRequest.STATUS_AWAITING_PAYMENT,
                PrintRequest.STATUS_CANCELLED,
            }
            <= statuses
        )
        self.assertTrue(PrintJob.objects.filter(job_status=PrintJob.STATUS_QUEUED).exists())
        self.assertIn("Password: Demo-pass-123", out.getvalue())
        self.assertTrue(self.client.login(username="demo_student", password="Demo-pass-123"))

    def test_refuses_to_run_twice(self):
        call_command("seed_demo", stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=StringIO())


class LoadTestUsersCommandTests(ChapifyTestCase):
    def test_creates_and_deletes_accounts(self):
        from django.contrib.auth.models import User
        from django.core.management import call_command

        call_command("create_loadtest_users", "--count", "3", stdout=StringIO())
        call_command("create_loadtest_users", "--count", "3", stdout=StringIO())  # idempotent
        self.assertEqual(User.objects.filter(username__startswith="loadtest_").count(), 3)
        self.assertTrue(User.objects.get(username="loadtest_002").check_password("Load-test-pass-2026"))
        call_command("create_loadtest_users", "--delete", stdout=StringIO())
        self.assertFalse(User.objects.filter(username__startswith="loadtest_").exists())
