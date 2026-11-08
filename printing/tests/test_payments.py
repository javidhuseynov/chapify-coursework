"""Payments through an external gateway: only the gateway can confirm a payment.

The gateway's HTTP API is replaced by FakeGateway; the real gateway
(gateway_service/) has its own tests, and CI runs both servers together.
"""

import json
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from printing import payment_gateways, services
from printing.models import AuditLog, PaymentTransaction, PrintJob, PrintRequest
from printing.payment_gateways import GatewayUnavailable, signature_header

from .base import ChapifyTestCase, gateway_result, pdf_file


class FakeGateway:
    """Stands in for Chapify Pay's HTTP API (printing.payment_gateways.http_request)."""

    def __init__(self):
        self.sessions = {}
        self.calls = []
        self.down = False

    def __call__(self, method, url, headers, json_body=None, form=None, timeout=10):
        self.calls.append((method, url, headers, json_body))
        if self.down:
            raise GatewayUnavailable("The payment service cannot be reached right now. Please try again in a minute.")
        if headers.get("Authorization") != f"Bearer {settings.CHAPIFY_PAY_API_KEY}":
            return 401, {"error": "Invalid API key."}
        if method == "POST":
            session_id = f"cs_test_{len(self.sessions) + 1}"
            self.sessions[session_id] = {
                "id": session_id,
                "url": f"http://127.0.0.1:8001/pay/{session_id}/",
                "status": "open",
                "payment_status": "unpaid",
                "merchant_reference": json_body["merchant_reference"],
                "amount": json_body["amount"],
                "currency": json_body["currency"],
                "expires_at": int((timezone.now() + timedelta(minutes=30)).timestamp()),
                "payment": None,
                "success_url": json_body["success_url"],
                "cancel_url": json_body["cancel_url"],
            }
            return 201, self.sessions[session_id]
        session = self.sessions.get(url.rstrip("/").rsplit("/", 1)[-1])
        return (200, session) if session else (404, {"error": "No such checkout session."})

    def pay(self, session_id, declined=False, payment_id="pay_test_1"):
        session = self.sessions[session_id]
        session.update(
            status="failed" if declined else "complete",
            payment_status="declined" if declined else "paid",
            payment={"id": payment_id, "status": "declined" if declined else "succeeded"},
        )
        return session


def webhook(session, event_type="checkout.session.completed", secret=None, timestamp=None):
    body = json.dumps({"id": "evt_test_1", "type": event_type, "data": {"object": session}}).encode()
    header = signature_header(secret or settings.CHAPIFY_PAY_WEBHOOK_SECRET, body, timestamp=timestamp)
    return body, header


class GatewayTestCase(ChapifyTestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        patcher = mock.patch.object(payment_gateways, "http_request", self.gateway)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user = self.make_user()
        self.print_request = self.make_request(self.user)

    def post_webhook(self, body, header):
        return self.client.post(
            reverse("payment_webhook"), data=body, content_type="application/json",
            HTTP_CHAPIFY_PAY_SIGNATURE=header,
        )


class CheckoutFlowTests(GatewayTestCase):
    """Browser flow: Chapify -> gateway checkout page -> back to Chapify."""

    def setUp(self):
        super().setUp()
        self.client.login(username="alice", password="Str0ng-test-pass!")

    def press_pay(self):
        response = self.client.post(reverse("payment", args=[self.print_request.id]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("http://127.0.0.1:8001/pay/cs_test_"))
        return list(self.gateway.sessions.values())[-1]

    def come_back(self, session):
        return self.client.get(f"{session['success_url']}&session_id={session['id']}")

    def test_checkout_session_is_created_server_to_server(self):
        session = self.press_pay()
        method, url, headers, body = self.gateway.calls[0]
        self.assertEqual((method, url), ("POST", "http://127.0.0.1:8001/v1/checkout/sessions"))
        self.assertEqual(body["amount"], "4.00")
        self.assertEqual(body["currency"], "EUR")
        payment = PaymentTransaction.objects.get()
        self.assertEqual(body["merchant_reference"], str(payment.reference))
        self.assertEqual(payment.gateway_session_id, session["id"])
        self.assertTrue(body["success_url"].startswith("http://testserver/payments/return/?payment="))

    def test_paid_on_return_even_without_webhook(self):
        session = self.press_pay()
        self.gateway.pay(session["id"])
        response = self.come_back(session)

        self.assertRedirects(response, reverse("request_status", args=[self.print_request.id]))
        self.print_request.refresh_from_db()
        self.assertEqual(self.print_request.status, PrintRequest.STATUS_PAYMENT_CONFIRMED)
        payment = self.confirmed_payments(self.print_request).get()
        self.assertEqual(payment.gateway_reference, "pay_test_1")
        self.assertEqual(PrintJob.objects.get(print_request=self.print_request).job_status, PrintJob.STATUS_QUEUED)
        # The file is kept until the job has actually been printed.
        self.assertTrue(self.print_request.document.has_file())

    def test_return_url_cannot_claim_a_payment(self):
        session = self.press_pay()  # not paid at the gateway
        self.come_back(session)
        self.print_request.refresh_from_db()
        self.assertEqual(self.print_request.status, PrintRequest.STATUS_AWAITING_PAYMENT)

        # A session id that belongs to another payment attempt is refused.
        payment = PaymentTransaction.objects.get()
        response = self.client.get(
            reverse("payment_return"), {"payment": str(payment.reference), "session_id": "cs_test_999"}, follow=True
        )
        self.assertContains(response, "Payment notification refused")
        self.assertFalse(PrintJob.objects.exists())

    def test_declined_payment_can_be_retried(self):
        first = self.press_pay()
        self.gateway.pay(first["id"], declined=True, payment_id="pay_test_declined")
        self.come_back(first)
        self.print_request.refresh_from_db()
        self.assertEqual(self.print_request.status, PrintRequest.STATUS_PAYMENT_REJECTED)
        self.assertTrue(self.print_request.document.has_file())

        second = self.press_pay()
        self.assertNotEqual(second["id"], first["id"])
        self.gateway.pay(second["id"], payment_id="pay_test_ok")
        self.come_back(second)
        self.print_request.refresh_from_db()
        self.assertEqual(self.print_request.status, PrintRequest.STATUS_PAYMENT_CONFIRMED)
        self.assertEqual(self.print_request.payments.count(), 2)
        self.assertEqual(self.confirmed_payments(self.print_request).count(), 1)

    def test_pressing_pay_twice_reuses_the_checkout(self):
        first = self.press_pay()
        second = self.press_pay()
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.gateway.calls), 1)
        self.assertEqual(self.print_request.payments.count(), 1)

    def test_expired_checkout_gets_a_new_attempt(self):
        self.press_pay()
        PaymentTransaction.objects.update(session_expires_at=timezone.now() + timedelta(seconds=30))
        self.press_pay()
        self.assertEqual(self.print_request.payments.count(), 2)
        self.assertEqual(self.print_request.payments.filter(payment_status="INITIATED").count(), 1)

    def test_cancel_at_the_gateway_returns_to_the_payment_page(self):
        session = self.press_pay()
        response = self.client.get(session["cancel_url"], follow=True)
        self.assertRedirects(response, reverse("payment", args=[self.print_request.id]))
        self.assertContains(response, "You have not been charged")

    def test_gateway_down_shows_a_clear_message(self):
        self.gateway.down = True
        response = self.client.post(reverse("payment", args=[self.print_request.id]), follow=True)
        self.assertContains(response, "cannot be reached right now")
        self.print_request.refresh_from_db()
        self.assertEqual(self.print_request.status, PrintRequest.STATUS_AWAITING_PAYMENT)

    def test_user_cannot_confirm_own_payment(self):
        self.client.post(reverse("payment", args=[self.print_request.id]), {"action": "confirm"})
        for suffix in ("confirm", "reject"):
            response = self.client.post(f"/api/requests/{self.print_request.id}/payment/{suffix}/")
            self.assertEqual(response.status_code, 404)
        self.print_request.refresh_from_db()
        self.assertEqual(self.print_request.status, PrintRequest.STATUS_AWAITING_PAYMENT)
        self.assertFalse(PrintJob.objects.exists())

    def test_payment_page_allows_the_redirect_to_the_gateway(self):
        response = self.client.get(reverse("payment", args=[self.print_request.id]))
        self.assertIn("form-action 'self' http://127.0.0.1:8001", response["Content-Security-Policy"])


class WebhookTests(GatewayTestCase):
    """The webhook endpoint accepts only valid, matching, fresh, signed events."""

    def setUp(self):
        super().setUp()
        self.payment = services.initiate_payment(self.print_request, self.user)
        self.session = self.gateway(
            "POST", "x", {"Authorization": f"Bearer {settings.CHAPIFY_PAY_API_KEY}"},
            json_body={
                "merchant_reference": str(self.payment.reference), "amount": "4.00", "currency": "EUR",
                "success_url": "http://testserver/r/", "cancel_url": "http://testserver/c/",
            },
        )[1]

    def assert_not_paid(self):
        self.payment.refresh_from_db()
        self.print_request.refresh_from_db()
        self.assertEqual(self.payment.payment_status, PaymentTransaction.STATUS_INITIATED)
        self.assertEqual(self.print_request.status, PrintRequest.STATUS_AWAITING_PAYMENT)
        self.assertFalse(PrintJob.objects.exists())

    def test_valid_webhook_confirms_payment(self):
        response = self.post_webhook(*webhook(self.gateway.pay(self.session["id"])))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"], "confirmed")
        self.assertEqual(PrintJob.objects.filter(print_request=self.print_request).count(), 1)

    def test_declined_webhook_rejects_payment(self):
        session = self.gateway.pay(self.session["id"], declined=True)
        response = self.post_webhook(*webhook(session, "checkout.session.payment_failed"))
        self.assertEqual(response.json()["result"], "rejected")
        self.print_request.refresh_from_db()
        self.assertEqual(self.print_request.status, PrintRequest.STATUS_PAYMENT_REJECTED)

    def test_replayed_webhook_has_effect_only_once(self):
        body, header = webhook(self.gateway.pay(self.session["id"]))
        self.assertEqual(self.post_webhook(body, header).json()["result"], "confirmed")
        second = self.post_webhook(body, header)
        self.assertEqual(second.json()["result"], "duplicate")
        self.assertEqual(self.confirmed_payments(self.print_request).count(), 1)
        self.assertEqual(PrintJob.objects.filter(print_request=self.print_request).count(), 1)

    def test_tampered_body_is_refused_and_audited(self):
        body, header = webhook(self.gateway.pay(self.session["id"]))
        response = self.post_webhook(body.replace(b'"4.00"', b'"0.01"'), header)
        self.assertEqual(response.status_code, 400)
        self.assert_not_paid()
        self.assertTrue(AuditLog.objects.filter(event_type=AuditLog.EVENT_PAYMENT_NOTIFICATION_REFUSED).exists())

    def test_wrong_secret_or_missing_signature_is_refused(self):
        body, header = webhook(self.gateway.pay(self.session["id"]), secret="whsec_attacker")
        self.assertEqual(self.post_webhook(body, header).status_code, 400)
        response = self.client.post(reverse("payment_webhook"), data=body, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assert_not_paid()

    def test_old_webhook_is_refused(self):
        body, header = webhook(self.gateway.pay(self.session["id"]), timestamp=1_000_000)
        self.assertEqual(self.post_webhook(body, header).status_code, 400)
        self.assert_not_paid()

    def test_amount_mismatch_is_refused(self):
        session = self.gateway.pay(self.session["id"])
        session["amount"] = "0.01"
        self.assertEqual(self.post_webhook(*webhook(session)).status_code, 400)
        self.assert_not_paid()

    def test_unknown_reference_is_refused(self):
        session = self.gateway.pay(self.session["id"])
        session["merchant_reference"] = "00000000-0000-0000-0000-000000000000"
        self.assertEqual(self.post_webhook(*webhook(session)).status_code, 400)
        self.assert_not_paid()

    def test_other_event_types_are_ignored(self):
        response = self.post_webhook(*webhook(self.session, "checkout.session.expired"))
        self.assertEqual(response.json()["result"], "ignored")
        self.assert_not_paid()

    def test_webhook_for_cancelled_request_is_refused(self):
        services.cancel_print_request(self.print_request, self.user)
        self.assertEqual(self.post_webhook(*webhook(self.gateway.pay(self.session["id"]))).status_code, 400)
        self.assertFalse(PrintJob.objects.exists())

    def test_webhook_for_superseded_attempt_is_refused(self):
        services.update_print_request(self.print_request, services.PrintOptions(1, "BW", "A4", "ONE_SIDED"), self.user)
        self.assertEqual(self.post_webhook(*webhook(self.gateway.pay(self.session["id"]))).status_code, 400)
        self.assertFalse(PrintJob.objects.exists())

    def test_conflicting_second_result_is_refused(self):
        services.apply_payment_notification(gateway_result(self.payment, "APPROVED"))
        with self.assertRaises(services.WorkflowError):
            services.apply_payment_notification(
                gateway_result(self.payment, "DECLINED", gateway_transaction_id="pay_test_other")
            )
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payment_status, PaymentTransaction.STATUS_CONFIRMED)

    def test_webhook_only_accepts_post(self):
        self.assertEqual(self.client.get(reverse("payment_webhook")).status_code, 405)


class ApiPaymentTests(GatewayTestCase):
    def setUp(self):
        super().setUp()
        self.client.login(username="alice", password="Str0ng-test-pass!")

    def test_api_create_and_initiate_payment(self):
        response = self.client.post(
            "/api/requests/create/",
            {"file": pdf_file(), "copies": 2, "color_mode": "COLOR", "paper_format": "A4", "duplex_mode": "ONE_SIDED"},
        )
        self.assertEqual(response.status_code, 201)
        request_id = response.json()["print_request"]["id"]
        self.assertEqual(response.json()["print_request"]["total_price"], "4.00")

        response = self.client.post(f"/api/requests/{request_id}/payment/")
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual((body["amount"], body["payment_status"]), ("4.00", "INITIATED"))
        self.assertTrue(body["checkout_url"].startswith("http://127.0.0.1:8001/pay/cs_test_"))

    def test_api_initiate_payment_refused_when_already_paid(self):
        paid = self.make_paid_request(self.user)
        self.assertEqual(self.client.post(f"/api/requests/{paid.id}/payment/").status_code, 409)

    def test_api_reports_gateway_down(self):
        self.gateway.down = True
        response = self.client.post(f"/api/requests/{self.print_request.id}/payment/")
        self.assertEqual(response.status_code, 503)


class StripeAdapterTests(ChapifyTestCase):
    """Stripe in test mode: same flow, Stripe's formats. Live keys are refused."""

    def test_live_keys_are_refused(self):
        for key in ("sk_live_123", "", "pk_test_123"):
            with self.assertRaises(ImproperlyConfigured):
                payment_gateways.check_stripe_key(key)
        payment_gateways.check_stripe_key("sk_test_123")

    @override_settings(STRIPE_SECRET_KEY="sk_test_abc", STRIPE_WEBHOOK_SECRET="whsec_stripe")
    def test_checkout_request_and_webhook(self):
        user = self.make_user()
        print_request = self.make_request(user)
        payment = services.initiate_payment(print_request, user)
        gateway = payment_gateways.StripeGateway()

        reply = {"id": "cs_test_stripe", "url": "https://checkout.stripe.com/c/pay/cs_test_stripe", "expires_at": 2_000_000_000}
        with mock.patch.object(payment_gateways, "http_request", return_value=(200, reply)) as http:
            session = gateway.create_checkout(payment, "https://chapify.example/payments/return/?payment=x", "https://c")
        method, url, headers = http.call_args.args[:3]
        form = dict(http.call_args.kwargs["form"])
        self.assertEqual((method, url), ("POST", "https://api.stripe.com/v1/checkout/sessions"))
        self.assertEqual(headers["Authorization"], "Bearer sk_test_abc")
        self.assertEqual(form["line_items[0][price_data][unit_amount]"], "400")
        self.assertEqual(form["client_reference_id"], str(payment.reference))
        self.assertTrue(form["success_url"].endswith("&session_id={CHECKOUT_SESSION_ID}"))
        self.assertEqual(session.url, reply["url"])

        stripe_session = {
            "id": "cs_test_stripe", "payment_status": "paid", "amount_total": 400, "currency": "eur",
            "client_reference_id": str(payment.reference), "payment_intent": "pi_test_1",
        }
        body = json.dumps({"type": "checkout.session.completed", "livemode": False,
                           "data": {"object": stripe_session}}).encode()
        result = gateway.parse_webhook(body, {"Stripe-Signature": signature_header("whsec_stripe", body)})
        self.assertEqual(result.as_notification(), gateway_result(payment, gateway_transaction_id="pi_test_1"))

        live = json.dumps({"type": "checkout.session.completed", "livemode": True, "data": {"object": stripe_session}}).encode()
        with self.assertRaises(payment_gateways.InvalidWebhook):
            gateway.parse_webhook(live, {"Stripe-Signature": signature_header("whsec_stripe", live)})
