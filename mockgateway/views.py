"""Simulated external payment gateway ("Chapify Pay - test mode").

It plays the role of a third-party hosted checkout page. It knows nothing
about Chapify's database: it only receives a signed checkout session, lets
the tester approve or decline the payment, and returns a signed payment
notification to the merchant's return URL. No card data is requested or
stored. Approving here is the equivalent of using a gateway test card.
"""

import uuid
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from . import signing

DECISIONS = {"approve": "APPROVED", "decline": "DECLINED"}


def _read_session(token):
    session = signing.unsign(
        token,
        settings.PAYMENT_GATEWAY_SECRET,
        max_age=settings.PAYMENT_SESSION_MAX_AGE_SECONDS,
    )

    required = ("reference", "amount", "currency", "return_url")
    if any(not session.get(key) for key in required):
        raise signing.BadSignature("Incomplete checkout session.")

    if urlsplit(session["return_url"]).scheme not in ("http", "https"):
        raise signing.BadSignature("Invalid return URL.")

    return session


def _error(request, message):
    return render(request, "mockgateway/error.html", {"message": message}, status=400)


@require_http_methods(["GET", "POST"])
def checkout(request):
    token = request.GET.get("session") or request.POST.get("session", "")

    try:
        session = _read_session(token)
    except signing.ExpiredSignature:
        return _error(request, "This checkout session has expired. Return to Chapify and start the payment again.")
    except signing.BadSignature:
        return _error(request, "Invalid checkout session.")

    if request.method == "POST":
        status = DECISIONS.get(request.POST.get("decision"))

        if status is None:
            return _error(request, "Unknown payment decision.")

        notification = signing.sign(
            {
                "reference": session["reference"],
                "amount": session["amount"],
                "currency": session["currency"],
                "status": status,
                "gateway_transaction_id": f"MOCK-{uuid.uuid4().hex[:12].upper()}",
            },
            settings.PAYMENT_GATEWAY_SECRET,
        )
        separator = "&" if "?" in session["return_url"] else "?"
        return HttpResponseRedirect(
            f"{session['return_url']}{separator}{urlencode({'notification': notification})}"
        )

    return render(request, "mockgateway/checkout.html", {"session": session, "token": token})
