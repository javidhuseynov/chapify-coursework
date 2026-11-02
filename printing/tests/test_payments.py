"""Gateway-style payment: only signed gateway notifications can confirm a payment."""

import json

from django.conf import settings
from django.urls import reverse

from mockgateway import signing
from printing import services
from printing.models import AuditLog, PaymentTransaction, PrintJob, PrintRequest

from .base import ChapifyTestCase, query_param, sign_notification


class GatewayCheckoutFlowTests(ChapifyTestCase):
    """End-to-end through the browser pages: Chapify -> mock gateway -> Chapify."""

    def setUp(self):
        self.user = self.make_user()
        self.client.login(username="alice", password="Str0ng-test-pass!")
        self.print_request = self.make_request(self.user)

    def go_to_gateway(self):
        response = self.client.post(reverse("payment", args=[self.print_request.id]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse("mockgateway:checkout")))
        return response["Location"]

    def decide(self, checkout_url, decision):
        page = self.client.get(checkout_url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "4.00 EUR")

        response = self.client.post(
            reverse("mockgateway:checkout"),
            {"session": query_param(checkout_url, "session"), "decision": decision},
        )
        self.assertEqual(response.status_code, 302)
        return response["Location"]  # Chapify return URL with the signed notification

    def test_approved_payment_confirms_and_queues_print_job(self):
        return_url = self.decide(self.go_to_gateway(), "approve")
        response = self.client.get(return_url)
        self.assertRedirects(response, reverse("request_status", args=[self.print_request.id]))

        self.print_request.refresh_from_db()
        self.assertEqual(self.print_request.status, PrintRequest.STATUS_PAYMENT_CONFIRMED)
        payment = self.confirmed_payments(self.print_request).get()
        self.assertTrue(payment.gateway_reference.startswith("MOCK-"))
        job = PrintJob.objects.get(print_request=self.print_request)
        self.assertEqual(job.job_status, PrintJob.STATUS_QUEUED)
        # The file is kept until the job has actually been printed.
        self.assertTrue(self.print_request.document.has_file())

        status_page = self.client.get(reverse("request_status", args=[self.print_request.id]))
        self.assertContains(status_page, "Queued")

    def test_declined_payment_can_be_retried(self):
        return_url = self.decide(self.go_to_gateway(), "decline")
        self.client.get(return_url)

        self.print_request.refresh_from_db()
        self.assertEqual(self.print_request.status, PrintRequest.STATUS_PAYMENT_REJECTED)
        self.assertFalse(PrintJob.objects.filter(print_request=self.print_request).exists())
        self.assertTrue(self.print_request.document.has_file())

        return_url = self.decide(self.go_to_gateway(), "approve")
        self.client.get(return_url)

        self.print_request.refresh_from_db()
        self.assertEqual(self.print_request.status, PrintRequest.STATUS_PAYMENT_CONFIRMED)
        self.assertEqual(self.print_request.payments.count(), 2)
        self.assertEqual(self.confirmed_payments(self.print_request).count(), 1)

    def test_pressing_pay_twice_reuses_the_open_attempt(self):
        self.go_to_gateway()
        self.go_to_gateway()
        self.assertEqual(self.print_request.payments.count(), 1)

    def test_amount_in_checkout_session_cannot_be_changed(self):
        checkout_url = self.go_to_gateway()
        token = query_param(checkout_url, "session")
        body, signature = token.split(".")
        cheap_body = signing.sign({"amount": "0.01"}, "x").split(".")[0]

        response = self.client.get(reverse("mockgateway:checkout"), {"session": f"{cheap_body}.{signature}"})
        self.assertEqual(response.status_code, 400)

    def test_user_cannot_confirm_own_payment(self):
        # The old "simulate successful payment" form field has no effect any more.
        self.client.post(reverse("payment", args=[self.print_request.id]), {"action": "confirm"})
        self.print_request.refresh_from_db()
        self.assertEqual(self.print_request.status, PrintRequest.STATUS_AWAITING_PAYMENT)
        self.assertFalse(self.confirmed_payments(self.print_request).exists())

        # The old API endpoints no longer exist.
        for suffix in ("confirm", "reject"):
            response = self.client.post(f"/api/requests/{self.print_request.id}/payment/{suffix}/")
            self.assertEqual(response.status_code, 404)

        self.assertFalse(PrintJob.objects.exists())


class NotificationSecurityTests(ChapifyTestCase):
    """The webhook endpoint accepts only valid, matching, fresh, signed notifications."""

    def setUp(self):
        self.user = self.make_user()
        self.print_request = self.make_request(self.user)
        self.payment = services.initiate_payment(self.print_request, self.user)
        self.callback_url = reverse("payment_callback")

    def post_notification(self, token):
        return self.client.post(self.callback_url, {"notification": token})

    def assert_not_paid(self):
        self.payment.refresh_from_db()
        self.print_request.refresh_from_db()
        self.assertEqual(self.payment.payment_status, PaymentTransaction.STATUS_INITIATED)
        self.assertEqual(self.print_request.status, PrintRequest.STATUS_AWAITING_PAYMENT)
        self.assertFalse(PrintJob.objects.exists())

    def test_valid_notification_is_accepted(self):
        response = self.post_notification(sign_notification(self.payment))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"], "confirmed")
        self.assertEqual(PrintJob.objects.filter(print_request=self.print_request).count(), 1)

    def test_json_body_is_accepted(self):
        response = self.client.post(
            self.callback_url,
            data=json.dumps({"notification": sign_notification(self.payment)}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

    def test_replayed_notification_has_effect_only_once(self):
        token = sign_notification(self.payment)
        first = self.post_notification(token)
        second = self.post_notification(token)

        self.assertEqual(first.json()["result"], "confirmed")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["result"], "duplicate")
        self.assertEqual(self.confirmed_payments(self.print_request).count(), 1)
        self.assertEqual(PrintJob.objects.filter(print_request=self.print_request).count(), 1)

    def test_tampered_notification_is_refused_and_audited(self):
        token = sign_notification(self.payment)
        body, signature = token.split(".")
        forged = signing.sign({"reference": str(self.payment.reference), "status": "APPROVED"}, "x").split(".")[0]

        response = self.post_notification(f"{forged}.{signature}")
        self.assertEqual(response.status_code, 400)
        self.assert_not_paid()
        self.assertTrue(AuditLog.objects.filter(event_type=AuditLog.EVENT_PAYMENT_NOTIFICATION_REFUSED).exists())

    def test_notification_signed_with_wrong_secret_is_refused(self):
        token = signing.sign(
            {
                "reference": str(self.payment.reference),
                "amount": str(self.payment.amount),
                "currency": "EUR",
                "status": "APPROVED",
                "gateway_transaction_id": "FAKE",
            },
            "attacker-secret",
        )
        self.assertEqual(self.post_notification(token).status_code, 400)
        self.assert_not_paid()

    def test_amount_mismatch_is_refused(self):
        response = self.post_notification(sign_notification(self.payment, amount="0.01"))
        self.assertEqual(response.status_code, 400)
        self.assert_not_paid()

    def test_unknown_reference_is_refused(self):
        response = self.post_notification(
            sign_notification(self.payment, reference="00000000-0000-0000-0000-000000000000")
        )
        self.assertEqual(response.status_code, 400)
        self.assert_not_paid()

    def test_expired_notification_is_refused(self):
        response = self.post_notification(sign_notification(self.payment, issued_at=1_000_000))
        self.assertEqual(response.status_code, 400)
        self.assert_not_paid()

    def test_notification_for_cancelled_request_is_refused(self):
        services.cancel_print_request(self.print_request, self.user)

        response = self.post_notification(sign_notification(self.payment))
        self.assertEqual(response.status_code, 400)
        self.print_request.refresh_from_db()
        self.assertEqual(self.print_request.status, PrintRequest.STATUS_CANCELLED)
        self.assertFalse(PrintJob.objects.exists())

    def test_notification_for_superseded_attempt_is_refused(self):
        # Price changed after checkout started -> old attempt cancelled, cannot complete.
        services.update_print_request(
            self.print_request,
            services.PrintOptions(1, "BW", "A4", "ONE_SIDED"),
            self.user,
        )
        self.assertEqual(self.post_notification(sign_notification(self.payment)).status_code, 400)
        self.assertFalse(PrintJob.objects.exists())

    def test_conflicting_second_result_is_refused(self):
        self.post_notification(sign_notification(self.payment, status="APPROVED"))
        response = self.post_notification(
            sign_notification(self.payment, status="DECLINED", gateway_transaction_id="MOCK-OTHER")
        )
        self.assertEqual(response.status_code, 400)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payment_status, PaymentTransaction.STATUS_CONFIRMED)

    def test_callback_only_accepts_post(self):
        self.assertEqual(self.client.get(self.callback_url).status_code, 405)

    def test_return_url_with_bad_notification_shows_error(self):
        self.client.login(username="alice", password="Str0ng-test-pass!")
        response = self.client.get(reverse("payment_return"), {"notification": "garbage"}, follow=True)
        self.assertContains(response, "Payment notification refused")
        self.assert_not_paid()


class ApiPaymentTests(ChapifyTestCase):
    def setUp(self):
        self.user = self.make_user()
        self.client.login(username="alice", password="Str0ng-test-pass!")

    def test_api_create_and_initiate_payment(self):
        from .base import pdf_file

        response = self.client.post(
            "/api/requests/create/",
            {
                "file": pdf_file(),
                "document_pages": 10,
                "copies": 2,
                "color_mode": "COLOR",
                "paper_format": "A4",
                "duplex_mode": "ONE_SIDED",
            },
        )
        self.assertEqual(response.status_code, 201)
        request_id = response.json()["print_request"]["id"]
        self.assertEqual(response.json()["print_request"]["total_price"], "4.00")

        response = self.client.post(f"/api/requests/{request_id}/payment/")
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["amount"], "4.00")
        self.assertEqual(body["payment_status"], "INITIATED")
        self.assertIn("/mock-gateway/checkout/?session=", body["checkout_url"])

    def test_api_initiate_payment_refused_when_already_paid(self):
        paid = self.make_paid_request(self.user)
        response = self.client.post(f"/api/requests/{paid.id}/payment/")
        self.assertEqual(response.status_code, 409)

    def test_settings_secret_is_used_for_checkout_sessions(self):
        print_request = self.make_request(self.user)
        response = self.client.post(f"/api/requests/{print_request.id}/payment/")
        session = query_param(response.json()["checkout_url"], "session")
        data = signing.unsign(session, settings.PAYMENT_GATEWAY_SECRET)
        self.assertEqual(data["amount"], "4.00")
        self.assertTrue(data["return_url"].endswith(reverse("payment_return")))
