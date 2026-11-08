"""Gateway logic: create sessions, take card payments, send webhooks."""

import json
import urllib.error
import urllib.request
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import CheckoutSession, Payment, WebhookEvent
from .signing import signature_header


class GatewayError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def origin(url):
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""


def create_session(merchant, data):
    """Create (or return the identical open) checkout session. Returns (session, created)."""
    if not isinstance(data, dict):
        raise GatewayError("The request body must be a JSON object.")

    reference = str(data.get("merchant_reference", "")).strip()[:100]
    currency = str(data.get("currency", "")).upper()
    description = str(data.get("description", ""))[:200]
    success_url = str(data.get("success_url", ""))
    cancel_url = str(data.get("cancel_url", ""))

    try:
        amount = Decimal(str(data.get("amount"))).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError):
        raise GatewayError("amount must be a decimal number such as \"4.00\".")

    if not reference:
        raise GatewayError("merchant_reference is required.")
    if currency not in settings.CURRENCIES:
        raise GatewayError(f"currency must be one of {', '.join(settings.CURRENCIES)}.")
    if not settings.MIN_AMOUNT <= amount <= settings.MAX_AMOUNT:
        raise GatewayError(f"amount must be between {settings.MIN_AMOUNT} and {settings.MAX_AMOUNT}.")
    for name, url in (("success_url", success_url), ("cancel_url", cancel_url)):
        if origin(url) not in settings.ALLOWED_RETURN_ORIGINS:
            raise GatewayError(f"{name} must point to an allowed merchant site.")

    now = timezone.now()
    with transaction.atomic():
        if CheckoutSession.objects.filter(
            merchant=merchant["id"], merchant_reference=reference, status=CheckoutSession.STATUS_COMPLETE
        ).exists():
            raise GatewayError("This merchant reference has already been paid.", status=409)

        existing = CheckoutSession.objects.filter(
            merchant=merchant["id"],
            merchant_reference=reference,
            status=CheckoutSession.STATUS_OPEN,
            amount=amount,
            currency=currency,
            expires_at__gt=now + timedelta(minutes=2),
        ).first()
        if existing:
            return existing, False

        session = CheckoutSession.objects.create(
            merchant=merchant["id"],
            merchant_reference=reference,
            amount=amount,
            currency=currency,
            description=description,
            success_url=success_url,
            cancel_url=cancel_url,
            expires_at=now + timedelta(minutes=settings.CHECKOUT_SESSION_MINUTES),
        )
    return session, True


def expire_if_due(session):
    if session.status == CheckoutSession.STATUS_OPEN and session.expires_at <= timezone.now():
        CheckoutSession.objects.filter(pk=session.pk, status=CheckoutSession.STATUS_OPEN).update(
            status=CheckoutSession.STATUS_EXPIRED, closed_at=timezone.now()
        )
        session.refresh_from_db()
    return session


def session_json(session, base_url=""):
    payment = session.latest_payment()
    return {
        "id": session.id,
        "object": "checkout.session",
        "url": f"{base_url}/pay/{session.id}/" if base_url else f"/pay/{session.id}/",
        "status": session.status,
        "payment_status": session.payment_status,
        "merchant_reference": session.merchant_reference,
        "amount": str(session.amount),
        "currency": session.currency,
        "description": session.description,
        "created": int(session.created_at.timestamp()),
        "expires_at": int(session.expires_at.timestamp()),
        "payment": None if payment is None else {
            "id": payment.id,
            "status": payment.outcome,
            "decline_code": payment.decline_code or None,
            "card": {"brand": payment.card_brand, "last4": payment.card_last4},
        },
    }


def pay(session, card):
    """Charge a test card. ``card`` comes from forms.CardForm.cleaned_data.

    One payment per session: the session becomes complete (paid) or failed
    (declined), and a webhook event is queued and sent.
    """
    decline_code = card["decline_code"]
    new_status = CheckoutSession.STATUS_FAILED if decline_code else CheckoutSession.STATUS_COMPLETE

    with transaction.atomic():
        claimed = CheckoutSession.objects.filter(
            pk=session.pk, status=CheckoutSession.STATUS_OPEN, expires_at__gt=timezone.now()
        ).update(status=new_status, closed_at=timezone.now())
        if not claimed:
            raise GatewayError("This checkout session is no longer open.", status=409)

        payment = Payment.objects.create(
            session=session,
            outcome=Payment.OUTCOME_DECLINED if decline_code else Payment.OUTCOME_SUCCEEDED,
            decline_code=decline_code or "",
            card_brand=card["brand"],
            card_last4=card["number"][-4:],
        )
        session.refresh_from_db()
        event = WebhookEvent(
            type="checkout.session.payment_failed" if decline_code else "checkout.session.completed",
            session=session,
            next_attempt_at=timezone.now(),
        )
        event.save()
        event.payload = json.dumps(
            {
                "id": event.id,
                "object": "event",
                "type": event.type,
                "created": int(event.created_at.timestamp()),
                "livemode": False,
                "data": {"object": session_json(session)},
            }
        )
        event.save(update_fields=["payload"])
        transaction.on_commit(lambda: deliver(event))

    return payment


def cancel(session):
    CheckoutSession.objects.filter(pk=session.pk, status=CheckoutSession.STATUS_OPEN).update(
        status=CheckoutSession.STATUS_CANCELED, closed_at=timezone.now()
    )
    session.refresh_from_db()
    return session


def deliver(event):
    """Send one webhook event to the merchant. Returns True when it was accepted (2xx)."""
    merchant = settings.MERCHANT
    body = event.payload.encode("utf-8")
    request = urllib.request.Request(
        merchant["webhook_url"],
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "ChapifyPay-Webhooks/1.0",
            "Chapify-Pay-Signature": signature_header(merchant["webhook_secret"], body),
        },
    )
    code, error = None, ""
    try:
        with urllib.request.urlopen(request, timeout=settings.WEBHOOK_TIMEOUT_SECONDS) as response:
            code = response.status
    except urllib.error.HTTPError as http_error:
        code = http_error.code
        error = f"HTTP {http_error.code}"
    except (urllib.error.URLError, OSError) as network_error:
        error = str(getattr(network_error, "reason", network_error))[:200]

    now = timezone.now()
    attempts = event.attempts + 1
    delivered = code is not None and 200 <= code < 300
    delays = settings.WEBHOOK_RETRY_DELAYS
    WebhookEvent.objects.filter(pk=event.pk).update(
        attempts=attempts,
        last_attempt_at=now,
        last_response_code=code,
        last_error=error,
        delivered_at=now if delivered else None,
        next_attempt_at=None if delivered or attempts > len(delays) else now + timedelta(seconds=delays[attempts - 1]),
    )
    event.refresh_from_db()
    return delivered


def deliver_due(limit=10):
    """Retry webhooks that are due. Returns the number delivered."""
    due = WebhookEvent.objects.filter(
        delivered_at__isnull=True, next_attempt_at__isnull=False, next_attempt_at__lte=timezone.now()
    ).order_by("next_attempt_at")[:limit]
    return sum(1 for event in list(due) if deliver(event))
