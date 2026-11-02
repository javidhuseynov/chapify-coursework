"""Chapify's client for the payment gateway.

Flow (mirrors hosted-checkout gateways such as Stripe Checkout or Paysera):

1. Chapify creates a PaymentTransaction (INITIATED) and sends the payer to the
   gateway's checkout page with a *signed checkout session* (reference,
   amount, currency, return URL). The signature stops the payer from changing
   the amount in the URL.
2. The payer approves or declines on the gateway's page.
3. The gateway sends back a *signed payment notification* (to the return URL
   in the browser, and/or to the server callback URL).
4. Chapify trusts the result only if the signature is valid, the notification
   is recent, and reference/amount/currency match the stored attempt
   (services.apply_payment_notification).

The browser never decides the payment result: without the shared secret a
notification cannot be forged or altered.
"""

from urllib.parse import urlencode

from django.conf import settings
from django.urls import reverse

from mockgateway import signing

from . import services


class InvalidNotification(services.WorkflowError):
    pass


def build_checkout_url(request, payment):
    print_request = payment.print_request
    session = signing.sign(
        {
            "merchant": "chapify",
            "reference": str(payment.reference),
            "amount": str(payment.amount),
            "currency": payment.currency,
            "description": f"Chapify print request #{print_request.pk}",
            "return_url": request.build_absolute_uri(reverse("payment_return")),
        },
        settings.PAYMENT_GATEWAY_SECRET,
    )
    return f"{reverse('mockgateway:checkout')}?{urlencode({'session': session})}"


def verify_notification(token):
    """Return the notification data or raise InvalidNotification."""
    try:
        return signing.unsign(
            token,
            settings.PAYMENT_GATEWAY_SECRET,
            max_age=settings.PAYMENT_NOTIFICATION_MAX_AGE_SECONDS,
        )
    except signing.ExpiredSignature:
        services.audit(
            services.AuditLog.EVENT_PAYMENT_NOTIFICATION_REFUSED,
            "Payment notification refused: notification has expired.",
        )
        raise InvalidNotification("Payment notification refused: notification has expired.")
    except signing.BadSignature:
        services.audit(
            services.AuditLog.EVENT_PAYMENT_NOTIFICATION_REFUSED,
            "Payment notification refused: invalid signature.",
        )
        raise InvalidNotification("Payment notification refused: invalid signature.")


def handle_notification(token):
    """Verify and apply a gateway notification. Raises WorkflowError on refusal."""
    data = verify_notification(token)
    return services.apply_payment_notification(data)
