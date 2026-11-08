"""Pages seen by the payer (hosted checkout)."""

from django.conf import settings
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods, require_POST

from . import services
from .cards import CARD_LIST, DECLINE_MESSAGES
from .forms import CardForm
from .models import CheckoutSession


def with_session_id(url, session_id):
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}session_id={session_id}"


def index(request):
    return render(request, "checkout/index.html", {"cards": CARD_LIST})


@require_http_methods(["GET", "POST"])
def pay(request, session_id):
    session = services.expire_if_due(get_object_or_404(CheckoutSession, pk=session_id))
    services.deliver_due(limit=3)  # retry late webhooks while someone is using the gateway

    if session.status == CheckoutSession.STATUS_COMPLETE:
        return HttpResponseRedirect(with_session_id(session.success_url, session.id))
    if session.status == CheckoutSession.STATUS_FAILED:
        return render_result(request, session)
    if session.status != CheckoutSession.STATUS_OPEN:
        return render(request, "checkout/closed.html", {"session": session}, status=410)

    form = CardForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.pay(session, form.cleaned_data)
        except services.GatewayError:
            session.refresh_from_db()
            return render(request, "checkout/closed.html", {"session": session}, status=409)
        session.refresh_from_db()
        if session.status == CheckoutSession.STATUS_COMPLETE:
            return HttpResponseRedirect(with_session_id(session.success_url, session.id))
        return render_result(request, session)

    return render(
        request,
        "checkout/pay.html",
        {"session": session, "form": form, "cards": CARD_LIST, "merchant": settings.MERCHANT["name"]},
        status=400 if form.errors else 200,
    )


def render_result(request, session):
    payment = session.latest_payment()
    return render(
        request,
        "checkout/declined.html",
        {
            "session": session,
            "payment": payment,
            "message": DECLINE_MESSAGES.get(payment.decline_code, "Your card was declined."),
            "return_url": with_session_id(session.success_url, session.id),
        },
    )


@require_POST
def cancel(request, session_id):
    session = services.cancel(get_object_or_404(CheckoutSession, pk=session_id))
    return HttpResponseRedirect(session.cancel_url)
