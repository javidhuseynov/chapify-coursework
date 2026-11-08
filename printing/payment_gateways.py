"""Payment gateway clients.

Chapify never sees card details. It talks to a payment gateway in the same
way as with Stripe Checkout:

1. Chapify creates a *checkout session* at the gateway, server to server,
   authenticated with its secret API key: amount, currency, its own payment
   reference, and the pages to return to.
2. The payer is sent to the gateway's hosted checkout page and pays there.
3. The gateway reports the result in a *signed webhook* (server to server).
   Chapify verifies the signature (HMAC-SHA256 over timestamp and body, with
   a shared webhook secret) and the timestamp, then applies the result.
4. When the payer comes back, Chapify also asks the gateway's API for the
   session's result, so the payment is recorded even if a webhook is late.

The result is applied by services.apply_payment_notification, which checks
reference, amount and currency and is idempotent. The browser never decides
the result: it only tells Chapify which session to ask the gateway about.

Two gateways implement this interface:
- ChapifyPayGateway: the separate test gateway in gateway_service/ (default).
- StripeGateway: Stripe in test mode. Live keys are refused.
"""

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .services import WorkflowError

SIGNATURE_VERSION = "v1"


class GatewayUnavailable(WorkflowError):
    """The gateway could not be reached or refused the request."""


class InvalidWebhook(WorkflowError):
    """A webhook failed verification (signature, timestamp or format)."""


@dataclass
class CheckoutSession:
    id: str
    url: str
    expires_at: int  # Unix time


@dataclass
class PaymentResult:
    """A final payment result, in the form services.apply_payment_notification expects."""

    reference: str
    status: str  # "APPROVED" or "DECLINED"
    amount: str
    currency: str
    gateway_transaction_id: str

    def as_notification(self):
        return {
            "reference": self.reference,
            "status": self.status,
            "amount": self.amount,
            "currency": self.currency,
            "gateway_transaction_id": self.gateway_transaction_id,
        }


# --- Webhook signatures (same scheme as Stripe: "t=<unix>,v1=<hex hmac>") ----------

def compute_signature(secret, timestamp, body: bytes):
    message = f"{timestamp}.".encode("ascii") + body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def signature_header(secret, body: bytes, timestamp=None):
    timestamp = int(time.time()) if timestamp is None else int(timestamp)
    return f"t={timestamp},{SIGNATURE_VERSION}={compute_signature(secret, timestamp, body)}"


def verify_signature(header, body: bytes, secret, tolerance, now=None):
    """Raise InvalidWebhook unless ``header`` is a valid, recent signature of ``body``."""
    if not header or not secret:
        raise InvalidWebhook("missing signature")

    timestamp, signatures = None, []
    for item in header.split(","):
        key, _, value = item.strip().partition("=")
        if key == "t" and value.isdigit():
            timestamp = int(value)
        elif key == SIGNATURE_VERSION:
            signatures.append(value)

    if timestamp is None or not signatures:
        raise InvalidWebhook("malformed signature header")

    expected = compute_signature(secret, timestamp, body)
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise InvalidWebhook("invalid signature")

    current = int(time.time()) if now is None else int(now)
    if abs(current - timestamp) > tolerance:
        raise InvalidWebhook("signature timestamp outside the allowed window (possible replay)")


# --- HTTP -----------------------------------------------------------------------------

def http_request(method, url, headers, json_body=None, form=None, timeout=10):
    """Send a request; return (status, parsed JSON or None). Raises GatewayUnavailable."""
    data = None
    headers = dict(headers)
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif form is not None:
        data = urlencode(form).encode("ascii")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, raw = response.status, response.read(1024 * 1024)
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read(64 * 1024)
    except (urllib.error.URLError, OSError) as error:
        raise GatewayUnavailable(
            "The payment service cannot be reached right now. Please try again in a minute."
        ) from error

    try:
        return status, (json.loads(raw) if raw else None)
    except ValueError:
        return status, None


def _amount(value):
    try:
        return str(Decimal(str(value)).quantize(Decimal("0.01")))
    except (InvalidOperation, TypeError):
        raise InvalidWebhook("invalid amount")


# --- Chapify Pay (gateway_service/) ----------------------------------------------------

class ChapifyPayGateway:
    name = "chapify_pay"
    label = "Chapify Pay (test gateway)"

    def __init__(self):
        self.base_url = settings.CHAPIFY_PAY_URL.rstrip("/")
        self.api_key = settings.CHAPIFY_PAY_API_KEY
        self.webhook_secret = settings.CHAPIFY_PAY_WEBHOOK_SECRET

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}

    def create_checkout(self, payment, success_url, cancel_url):
        status, data = http_request(
            "POST",
            f"{self.base_url}/v1/checkout/sessions",
            self._headers(),
            json_body={
                "merchant_reference": str(payment.reference),
                "amount": str(payment.amount),
                "currency": payment.currency,
                "description": f"Chapify print request #{payment.print_request_id}",
                "success_url": success_url,
                "cancel_url": cancel_url,
            },
        )
        if status not in (200, 201) or not data:
            detail = (data or {}).get("error", f"HTTP {status}")
            raise GatewayUnavailable(f"The payment service refused the checkout ({detail}).")
        return CheckoutSession(data["id"], data["url"], int(data["expires_at"]))

    @staticmethod
    def _result(session):
        if session.get("payment_status") == "paid":
            result = "APPROVED"
        elif session.get("payment_status") == "declined":
            result = "DECLINED"
        else:
            return None  # still open, cancelled or expired: nothing to apply
        payment = session.get("payment") or {}
        return PaymentResult(
            reference=str(session.get("merchant_reference", "")),
            status=result,
            amount=_amount(session.get("amount")),
            currency=str(session.get("currency", "")),
            gateway_transaction_id=str(payment.get("id") or session.get("id", ""))[:100],
        )

    def retrieve(self, session_id):
        status, data = http_request("GET", f"{self.base_url}/v1/checkout/sessions/{session_id}", self._headers())
        if status != 200 or not data:
            raise GatewayUnavailable("The payment service could not confirm this payment yet.")
        return self._result(data)

    def parse_webhook(self, body, headers):
        verify_signature(
            headers.get("Chapify-Pay-Signature"),
            body,
            self.webhook_secret,
            settings.PAYMENT_WEBHOOK_TOLERANCE_SECONDS,
        )
        try:
            event = json.loads(body)
            session = event["data"]["object"]
        except (ValueError, KeyError, TypeError):
            raise InvalidWebhook("malformed event")
        if event.get("type") not in ("checkout.session.completed", "checkout.session.payment_failed"):
            return None
        return self._result(session)


# --- Stripe (test mode only) ----------------------------------------------------------

class StripeGateway:
    name = "stripe"
    label = "Stripe (test mode)"
    api_base = "https://api.stripe.com/v1"

    def __init__(self):
        self.secret_key = settings.STRIPE_SECRET_KEY
        self.webhook_secret = settings.STRIPE_WEBHOOK_SECRET
        check_stripe_key(self.secret_key)

    def _headers(self):
        return {"Authorization": f"Bearer {self.secret_key}", "Stripe-Version": "2024-06-20"}

    def create_checkout(self, payment, success_url, cancel_url):
        cents = int((payment.amount * 100).to_integral_value())
        form = [
            ("mode", "payment"),
            ("client_reference_id", str(payment.reference)),
            ("metadata[payment_reference]", str(payment.reference)),
            ("line_items[0][quantity]", "1"),
            ("line_items[0][price_data][currency]", payment.currency.lower()),
            ("line_items[0][price_data][unit_amount]", str(cents)),
            ("line_items[0][price_data][product_data][name]", f"Chapify print request #{payment.print_request_id}"),
            # Stripe replaces {CHECKOUT_SESSION_ID} with the session id.
            ("success_url", f"{success_url}&session_id={{CHECKOUT_SESSION_ID}}"),
            ("cancel_url", cancel_url),
        ]
        status, data = http_request("POST", f"{self.api_base}/checkout/sessions", self._headers(), form=form)
        if status != 200 or not data or "url" not in data:
            detail = ((data or {}).get("error") or {}).get("message", f"HTTP {status}")
            raise GatewayUnavailable(f"Stripe refused the checkout ({detail}).")
        return CheckoutSession(data["id"], data["url"], int(data["expires_at"]))

    @staticmethod
    def _result(session, declined=False):
        if not declined and session.get("payment_status") != "paid":
            return None
        cents = session.get("amount_total")
        if not isinstance(cents, int):
            raise InvalidWebhook("invalid amount")
        return PaymentResult(
            reference=str(session.get("client_reference_id") or (session.get("metadata") or {}).get("payment_reference", "")),
            status="DECLINED" if declined else "APPROVED",
            amount=_amount(Decimal(cents) / 100),
            currency=str(session.get("currency", "")).upper(),
            gateway_transaction_id=str(session.get("payment_intent") or session.get("id", ""))[:100],
        )

    def retrieve(self, session_id):
        status, data = http_request("GET", f"{self.api_base}/checkout/sessions/{session_id}", self._headers())
        if status != 200 or not data:
            raise GatewayUnavailable("Stripe could not confirm this payment yet.")
        return self._result(data)

    def parse_webhook(self, body, headers):
        verify_signature(
            headers.get("Stripe-Signature"),
            body,
            self.webhook_secret,
            settings.PAYMENT_WEBHOOK_TOLERANCE_SECONDS,
        )
        try:
            event = json.loads(body)
            session = event["data"]["object"]
        except (ValueError, KeyError, TypeError):
            raise InvalidWebhook("malformed event")
        if event.get("livemode"):
            raise InvalidWebhook("live-mode events are not accepted")
        if event.get("type") in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
            return self._result(session)
        if event.get("type") == "checkout.session.async_payment_failed":
            return self._result(session, declined=True)
        return None


def check_stripe_key(key):
    """Chapify must never move real money: only Stripe test keys are accepted."""
    if not key or not key.startswith(("sk_test_", "rk_test_")):
        raise ImproperlyConfigured(
            "Stripe needs a TEST secret key (sk_test_... or rk_test_...) in CHAPIFY_STRIPE_SECRET_KEY. "
            "Live keys are refused."
        )


GATEWAYS = {ChapifyPayGateway.name: ChapifyPayGateway, StripeGateway.name: StripeGateway}


def get_gateway(name=None):
    name = name or settings.PAYMENT_GATEWAY
    try:
        return GATEWAYS[name]()
    except KeyError:
        raise ImproperlyConfigured(f"Unknown payment gateway '{name}'. Use one of: {', '.join(GATEWAYS)}.")
