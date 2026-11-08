"""Chapify Pay: merchant API, hosted checkout and webhooks."""

import hashlib
import hmac
import json
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from checkout import services
from checkout.models import CheckoutSession, Payment, WebhookEvent

KEY = settings.MERCHANT["api_key"]
RETURN = "http://127.0.0.1:8000/payments/return/?payment=abc"


def session_data(**overrides):
    data = {
        "merchant_reference": "6f1c2c1e-0000-4000-8000-000000000001",
        "amount": "4.00",
        "currency": "EUR",
        "description": "Chapify print request #1",
        "success_url": RETURN,
        "cancel_url": RETURN + "&cancelled=1",
    }
    data.update(overrides)
    return data


class FakeResponse:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class GatewayTestCase(TestCase):
    def create(self, key=KEY, **overrides):
        return self.client.post(
            "/v1/checkout/sessions",
            data=json.dumps(session_data(**overrides)),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {key}",
        )

    def new_session(self, **overrides):
        response = self.create(**overrides)
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def pay(self, session_id, number="4242 4242 4242 4242", **overrides):
        data = {"name": "Test Student", "number": number, "expiry": "12/40", "cvc": "123"}
        data.update(overrides)
        with mock.patch("checkout.services.urllib.request.urlopen", return_value=FakeResponse(200)) as urlopen:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(f"/pay/{session_id}/", data)
        self.sent = urlopen.call_args_list
        return response


class MerchantApiTests(GatewayTestCase):
    def test_create_session(self):
        data = self.new_session()
        self.assertTrue(data["id"].startswith("cs_test_"))
        self.assertEqual(data["url"], f"http://testserver/pay/{data['id']}/")
        self.assertEqual((data["status"], data["payment_status"], data["amount"]), ("open", "unpaid", "4.00"))
        self.assertGreater(data["expires_at"], timezone.now().timestamp())

    def test_api_key_is_required(self):
        self.assertEqual(self.create(key="sk_test_wrong").status_code, 401)
        response = self.client.post("/v1/checkout/sessions", data="{}", content_type="application/json")
        self.assertEqual(response.status_code, 401)
        session_id = self.new_session()["id"]
        self.assertEqual(self.client.get(f"/v1/checkout/sessions/{session_id}").status_code, 401)

    def test_invalid_requests_are_refused(self):
        for overrides in (
            {"amount": "abc"},
            {"amount": "0"},
            {"amount": "5000"},
            {"currency": "USD"},
            {"merchant_reference": ""},
            {"success_url": "https://evil.example/steal"},
            {"cancel_url": "javascript:alert(1)"},
        ):
            self.assertEqual(self.create(**overrides).status_code, 400, overrides)

    def test_same_open_session_is_returned_for_the_same_reference(self):
        first = self.new_session()
        second = self.create()
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["id"], first["id"])
        self.assertEqual(self.create(amount="5.00").status_code, 201)  # different amount: new session

    def test_paid_reference_cannot_get_a_new_session(self):
        self.pay(self.new_session()["id"])
        self.assertEqual(self.create().status_code, 409)

    def test_read_session_with_result(self):
        session_id = self.new_session()["id"]
        self.pay(session_id)
        data = self.client.get(f"/v1/checkout/sessions/{session_id}", HTTP_AUTHORIZATION=f"Bearer {KEY}").json()
        self.assertEqual((data["status"], data["payment_status"]), ("complete", "paid"))
        self.assertEqual(data["payment"]["card"], {"brand": "visa", "last4": "4242"})

    def test_unknown_session(self):
        response = self.client.get("/v1/checkout/sessions/cs_test_nope", HTTP_AUTHORIZATION=f"Bearer {KEY}")
        self.assertEqual(response.status_code, 404)


class CheckoutPageTests(GatewayTestCase):
    def setUp(self):
        self.session_id = self.new_session()["id"]

    def test_page_shows_amount_and_test_cards(self):
        page = self.client.get(f"/pay/{self.session_id}/")
        self.assertContains(page, "4.00")
        self.assertContains(page, "Test mode")
        self.assertContains(page, "4242 4242 4242 4242")

    def test_successful_payment_redirects_back_and_sends_signed_webhook(self):
        response = self.pay(self.session_id)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{RETURN}&session_id={self.session_id}")

        payment = Payment.objects.get()
        self.assertEqual((payment.outcome, payment.card_last4), ("succeeded", "4242"))
        event = WebhookEvent.objects.get()
        self.assertEqual(event.type, "checkout.session.completed")
        self.assertIsNotNone(event.delivered_at)

        request = self.sent[0].args[0]
        self.assertEqual(request.full_url, settings.MERCHANT["webhook_url"])
        header = request.get_header("Chapify-pay-signature")
        timestamp = header.split(",")[0][2:]
        expected = hmac.new(
            settings.MERCHANT["webhook_secret"].encode(), f"{timestamp}.".encode() + request.data, hashlib.sha256
        ).hexdigest()
        self.assertEqual(header, f"t={timestamp},v1={expected}")
        body = json.loads(request.data)
        self.assertEqual(body["data"]["object"]["payment_status"], "paid")
        self.assertFalse(body["livemode"])

    def test_declined_card_shows_reason_and_sends_failed_event(self):
        response = self.pay(self.session_id, number="4000000000009995")
        self.assertContains(response, "insufficient funds")
        self.assertContains(response, f"session_id={self.session_id}")
        self.assertEqual(WebhookEvent.objects.get().type, "checkout.session.payment_failed")
        session = CheckoutSession.objects.get()
        self.assertEqual((session.status, session.payment_status), ("failed", "declined"))

    def test_only_test_cards_are_accepted_and_card_data_is_not_echoed_or_stored(self):
        real_looking = "4111 1111 1111 1111"  # valid checksum, not a test card
        response = self.pay(self.session_id, number=real_looking, cvc="987")
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "use one of the test card numbers", status_code=400)
        page = response.content.decode()
        self.assertNotIn("4111 1111", page)
        self.assertNotIn("987", page)
        self.assertFalse(Payment.objects.exists())

    def test_card_form_validation(self):
        for overrides in ({"number": "1234"}, {"expiry": "01/20"}, {"expiry": "13/40"}, {"cvc": "1"}, {"name": ""}):
            self.assertEqual(self.pay(self.session_id, **overrides).status_code, 400, overrides)
        self.assertFalse(Payment.objects.exists())

    def test_session_can_be_paid_only_once(self):
        self.pay(self.session_id)
        response = self.pay(self.session_id, number="5555555555554444")
        self.assertEqual(response.status_code, 302)  # straight back to the merchant
        self.assertEqual(Payment.objects.count(), 1)

    def test_cancel_returns_to_merchant(self):
        response = self.client.post(f"/pay/{self.session_id}/cancel/")
        self.assertEqual(response["Location"], RETURN + "&cancelled=1")
        self.assertEqual(CheckoutSession.objects.get().status, "canceled")
        self.assertEqual(self.client.get(f"/pay/{self.session_id}/").status_code, 410)

    def test_expired_session_cannot_be_paid(self):
        CheckoutSession.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.get(f"/pay/{self.session_id}/").status_code, 410)
        self.assertEqual(CheckoutSession.objects.get().status, "expired")

    def test_pages_have_security_headers(self):
        page = self.client.get(f"/pay/{self.session_id}/")
        self.assertIn("form-action 'self' http://127.0.0.1:8000", page["Content-Security-Policy"])
        self.assertEqual(page["X-Frame-Options"], "DENY")


class WebhookRetryTests(GatewayTestCase):
    def test_failed_delivery_is_retried_later(self):
        session_id = self.new_session()["id"]
        with mock.patch("checkout.services.urllib.request.urlopen", side_effect=OSError("connection refused")):
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(
                    f"/pay/{session_id}/", {"name": "A", "number": "4242424242424242", "expiry": "12/40", "cvc": "123"}
                )
        event = WebhookEvent.objects.get()
        self.assertIsNone(event.delivered_at)
        self.assertEqual(event.attempts, 1)
        self.assertGreater(event.next_attempt_at, timezone.now())

        WebhookEvent.objects.update(next_attempt_at=timezone.now())
        with mock.patch("checkout.services.urllib.request.urlopen", return_value=FakeResponse(200)):
            self.assertEqual(services.deliver_due(), 1)
        event.refresh_from_db()
        self.assertIsNotNone(event.delivered_at)
        self.assertEqual(event.attempts, 2)

    def test_retries_stop_after_the_last_delay(self):
        session_id = self.new_session()["id"]
        with mock.patch("checkout.services.urllib.request.urlopen", side_effect=OSError("down")):
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(
                    f"/pay/{session_id}/", {"name": "A", "number": "4242424242424242", "expiry": "12/40", "cvc": "123"}
                )
            event = WebhookEvent.objects.get()
            for _ in settings.WEBHOOK_RETRY_DELAYS:
                services.deliver(event)
        event.refresh_from_db()
        self.assertEqual(event.attempts, len(settings.WEBHOOK_RETRY_DELAYS) + 1)
        self.assertIsNone(event.next_attempt_at)
