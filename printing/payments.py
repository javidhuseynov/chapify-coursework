"""Payment flow between Chapify and the payment gateway.

See printing/payment_gateways.py for the protocol. This module connects it
to Chapify's pages and to services.apply_payment_notification.
"""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from . import services
from .models import AuditLog, PaymentTransaction
from .payment_gateways import GatewayUnavailable, InvalidWebhook, get_gateway


def start_checkout(request, payment):
    """Return the gateway checkout URL for ``payment``, creating the session if needed.

    The gateway is called outside any database transaction.
    """
    if (
        payment.checkout_url
        and payment.session_expires_at
        and payment.session_expires_at > timezone.now() + timedelta(minutes=2)
    ):
        return payment.checkout_url

    gateway = get_gateway()
    return_url = request.build_absolute_uri(reverse("payment_return"))
    session = gateway.create_checkout(
        payment,
        success_url=f"{return_url}?payment={payment.reference}",
        cancel_url=f"{return_url}?payment={payment.reference}&cancelled=1",
    )
    payment = services.attach_checkout_session(payment, gateway.name, session)
    return payment.checkout_url


def refuse(reason, payment=None):
    services.audit(
        AuditLog.EVENT_PAYMENT_NOTIFICATION_REFUSED,
        f"Payment notification refused: {reason}",
        print_request=payment.print_request if payment else None,
    )
    raise services.WorkflowError(f"Payment notification refused: {reason}")


def handle_webhook(body, headers):
    """Verify and apply a webhook. Returns a PaymentOutcome, or None for ignored events."""
    try:
        result = get_gateway().parse_webhook(body, headers)
    except InvalidWebhook as error:
        refuse(str(error))

    if result is None:
        return None
    return services.apply_payment_notification(result.as_notification())


def confirm_on_return(payment_reference, session_id):
    """The payer came back: ask the gateway (server to server) for the result.

    Returns (payment, outcome); outcome is None while the gateway has no
    final result yet.
    """
    payment = (
        PaymentTransaction.objects.select_related("print_request").filter(reference=payment_reference).first()
        if services.is_uuid(payment_reference)
        else None
    )

    if payment is None or not session_id or payment.gateway_session_id != session_id:
        refuse("the returning payer's session does not match a payment attempt.", payment)

    result = get_gateway(payment.gateway or None).retrieve(session_id)
    if result is None:
        return payment, None

    if result.reference != str(payment.reference):
        refuse(f"gateway session {session_id[:40]} belongs to another payment.", payment)

    return payment, services.apply_payment_notification(result.as_notification())


__all__ = ["GatewayUnavailable", "confirm_on_return", "handle_webhook", "start_checkout"]
