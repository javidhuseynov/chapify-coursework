"""M5: account management, printers, job retry and authentication audit events."""

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.authtoken.models import Token

from printing import services
from printing.models import AuditLog, Printer, PrintJob, PrintRequest, Profile

from .base import PASSWORD, ChapifyTestCase

User = get_user_model()


class AccountBlockingTests(ChapifyTestCase):
    def setUp(self):
        self.admin = self.make_admin()
        self.user = self.make_user()

    def block(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("admin_user_action", args=[self.user.pk]), {"action": "block"})
        self.client.logout()
        return response

    def test_blocking_sets_status_and_deactivates_account(self):
        self.assertRedirects(self.block(), reverse("admin_users"), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.profile.account_status, Profile.STATUS_BLOCKED)
        self.assertFalse(self.user.is_active)
        self.assertTrue(
            AuditLog.objects.filter(event_type=AuditLog.EVENT_USER_MANAGED, description__contains="BLOCKED").exists()
        )

    def test_blocked_user_cannot_log_in(self):
        self.block()
        self.assertFalse(self.client.login(username="alice", password=PASSWORD))

        response = self.client.post(reverse("login"), {"username": "alice", "password": PASSWORD})
        self.assertEqual(response.status_code, 200)  # login form shown again with an error
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_existing_session_ends_when_blocked(self):
        user_client = self.client_class()
        user_client.login(username="alice", password=PASSWORD)
        self.assertEqual(user_client.get(reverse("request_history")).status_code, 200)

        self.block()
        response = user_client.get(reverse("request_history"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_api_token_stops_working_when_blocked(self):
        token = Token.objects.create(user=self.user)
        self.block()
        self.assertFalse(Token.objects.filter(key=token.key).exists())

        response = self.client.get("/api/my/requests/", HTTP_AUTHORIZATION=f"Token {token.key}")
        self.assertIn(response.status_code, (401, 403))

    def test_unblocking_restores_access(self):
        self.block()
        services.set_account_status(self.user, Profile.STATUS_ACTIVE, self.admin)
        self.assertTrue(self.client.login(username="alice", password=PASSWORD))

    def test_admin_cannot_block_or_demote_themselves(self):
        with self.assertRaises(services.WorkflowError):
            services.set_account_status(self.admin, Profile.STATUS_BLOCKED, self.admin)
        with self.assertRaises(services.WorkflowError):
            services.set_role(self.admin, Profile.ROLE_USER, self.admin)

        self.client.force_login(self.admin)
        self.client.post(reverse("admin_user_action", args=[self.admin.pk]), {"action": "block"})
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_deactivating_in_django_admin_counts_as_blocked(self):
        self.user.is_active = False
        self.user.save()
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.account_status, Profile.STATUS_BLOCKED)


class RoleManagementTests(ChapifyTestCase):
    def setUp(self):
        self.admin = self.make_admin()
        self.user = self.make_user()

    def test_promote_and_demote(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("admin_user_action", args=[self.user.pk]), {"action": "make_admin"})
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.role, Profile.ROLE_ADMIN)

        self.client.post(reverse("admin_user_action", args=[self.user.pk]), {"action": "make_user"})
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.role, Profile.ROLE_USER)

    def test_normal_user_cannot_manage_accounts(self):
        other = self.make_user("bob")
        self.client.force_login(self.user)
        response = self.client.post(reverse("admin_user_action", args=[other.pk]), {"action": "block"})
        self.assertEqual(response.status_code, 403)
        other.refresh_from_db()
        self.assertTrue(other.is_active)

    def test_users_page_lists_and_filters(self):
        self.make_user("bob")
        services.set_account_status(User.objects.get(username="bob"), Profile.STATUS_BLOCKED, self.admin)
        self.client.force_login(self.admin)

        response = self.client.get(reverse("admin_users"), {"status": "BLOCKED"})
        self.assertContains(response, "bob")
        self.assertNotContains(response, "alice@example.com")

    def test_unknown_action_is_refused(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("admin_user_action", args=[self.user.pk]), {"action": "delete"}, follow=True)
        self.assertContains(response, "Unknown action")


class PrinterManagementTests(ChapifyTestCase):
    def setUp(self):
        self.admin = self.make_admin()
        self.client.force_login(self.admin)

    def test_add_printer(self):
        self.client.post(reverse("admin_printers"), {"printer_name": "Lab Printer", "location": "Room 101"})
        self.assertTrue(Printer.objects.filter(printer_name="Lab Printer", location="Room 101").exists())

    def test_add_printer_requires_fields(self):
        response = self.client.post(reverse("admin_printers"), {"printer_name": " ", "location": ""}, follow=True)
        self.assertContains(response, "required")

    def test_offline_printers_receive_no_jobs(self):
        user = self.make_user()
        Printer.objects.all().delete()
        printer = Printer.objects.create(printer_name="Only", location="L")
        self.client.post(reverse("admin_printer_status", args=[printer.pk]), {"printer_status": "OFFLINE"})
        printer.refresh_from_db()
        self.assertEqual(printer.printer_status, Printer.STATUS_OFFLINE)

        self.make_paid_request(user)
        self.assertIsNone(services.process_next_print_job())

        self.client.post(reverse("admin_printer_status", args=[printer.pk]), {"printer_status": "AVAILABLE"})
        self.assertEqual(services.process_next_print_job().job_status, PrintJob.STATUS_COMPLETED)

    def test_busy_status_cannot_be_set_or_changed_manually(self):
        printer = Printer.objects.create(printer_name="P", location="L")
        with self.assertRaises(services.WorkflowError):
            services.set_printer_status(printer, Printer.STATUS_BUSY, self.admin)

        Printer.objects.filter(pk=printer.pk).update(printer_status=Printer.STATUS_BUSY)
        with self.assertRaises(services.WorkflowError):
            services.set_printer_status(printer, Printer.STATUS_OFFLINE, self.admin)

    def test_transactions_page_filters(self):
        user = self.make_user()
        paid = self.make_paid_request(user)
        self.make_request(user)  # open request without payment

        response = self.client.get(reverse("admin_transactions"), {"status": "CONFIRMED"})
        self.assertContains(response, f"#{paid.id}")
        self.assertContains(response, "4.00 EUR")

        payment = self.confirmed_payments(paid).get()
        response = self.client.get(reverse("admin_transactions"), {"q": str(payment.reference)})
        self.assertContains(response, str(payment.reference))


class RetryPrintJobTests(ChapifyTestCase):
    def setUp(self):
        self.admin = self.make_admin()
        self.user = self.make_user()
        self.print_request = self.make_paid_request(self.user)
        self.job = services.process_next_print_job(force_failure=True)

    def test_retry_requeues_and_job_can_complete(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("admin_retry_print_job", args=[self.job.id]))
        self.assertRedirects(response, reverse("admin_dashboard"))

        self.job.refresh_from_db()
        self.print_request.refresh_from_db()
        self.assertEqual(self.job.job_status, PrintJob.STATUS_QUEUED)
        self.assertEqual(self.job.failure_reason, "")
        self.assertEqual(self.print_request.status, PrintRequest.STATUS_PAYMENT_CONFIRMED)

        finished = services.process_next_print_job()
        self.assertEqual(finished.job_status, PrintJob.STATUS_COMPLETED)
        self.print_request.refresh_from_db()
        self.assertEqual(self.print_request.status, PrintRequest.STATUS_COMPLETED)
        self.assertFalse(self.print_request.document.has_file())

    def test_retry_refused_when_file_is_gone(self):
        self.print_request.document.delete_file_from_storage()
        with self.assertRaises(services.WorkflowError):
            services.retry_print_job(self.job, self.admin)

    def test_only_failed_jobs_can_be_retried(self):
        services.retry_print_job(self.job, self.admin)
        with self.assertRaises(services.WorkflowError):
            services.retry_print_job(self.job, self.admin)

    def test_dashboard_shows_retry_button(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin_dashboard"))
        self.assertContains(response, reverse("admin_retry_print_job", args=[self.job.id]))

    def test_normal_user_cannot_retry(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(reverse("admin_retry_print_job", args=[self.job.id])).status_code, 403)


class AuthenticationAuditTests(ChapifyTestCase):
    def test_successful_login_and_logout_are_logged(self):
        user = self.make_user()
        self.client.post(reverse("login"), {"username": "alice", "password": PASSWORD})
        self.assertTrue(AuditLog.objects.filter(event_type=AuditLog.EVENT_LOGIN_SUCCESS, user=user).exists())

        self.client.post(reverse("logout"))
        self.assertTrue(AuditLog.objects.filter(event_type=AuditLog.EVENT_LOGOUT, user=user).exists())

    def test_failed_login_is_logged_without_password(self):
        self.make_user()
        self.client.post(reverse("login"), {"username": "alice", "password": "wrong-password"})

        log = AuditLog.objects.get(event_type=AuditLog.EVENT_LOGIN_FAILED)
        self.assertIn("alice", log.description)
        self.assertNotIn("wrong-password", log.description)

    def test_failed_api_token_request_is_logged(self):
        self.client.post("/api/auth/token/", {"username": "ghost", "password": "x"})
        self.assertTrue(
            AuditLog.objects.filter(event_type=AuditLog.EVENT_LOGIN_FAILED, description__contains="ghost").exists()
        )

    def test_registration_is_logged_once(self):
        from .base import registration_data

        self.client.post(reverse("register"), registration_data("newbie"))
        user = User.objects.get(username="newbie")
        self.assertEqual(AuditLog.objects.filter(event_type=AuditLog.EVENT_ACCOUNT_REGISTERED, user=user).count(), 1)
        self.assertEqual(AuditLog.objects.filter(event_type=AuditLog.EVENT_LOGIN_SUCCESS, user=user).count(), 1)
