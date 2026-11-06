from django import template
from django.utils.html import format_html

register = template.Library()

# One visual tone per status value, shared by requests, payments, jobs,
# printers and accounts so the same word always looks the same.
STATUS_TONES = {
    "AWAITING_PAYMENT": "wait",
    "INITIATED": "wait",
    "QUEUED": "info",
    "IN_PROGRESS": "info",
    "BUSY": "info",
    "PAYMENT_CONFIRMED": "info",
    "COMPLETED": "ok",
    "CONFIRMED": "ok",
    "AVAILABLE": "ok",
    "ACTIVE": "ok",
    "PAYMENT_REJECTED": "bad",
    "REJECTED": "bad",
    "FAILED": "bad",
    "ERROR": "bad",
    "BLOCKED": "bad",
    "CANCELLED": "neutral",
    "OFFLINE": "neutral",
    "DELETED": "neutral",
}


@register.filter
def status_tone(value):
    return STATUS_TONES.get(str(value), "neutral")


@register.simple_tag(takes_context=True)
def current(context, *url_names):
    """aria-current="page" when the current view is one of url_names."""
    request = context.get("request")
    match = getattr(request, "resolver_match", None)
    if match is not None and match.url_name in url_names:
        return format_html('aria-current="page"')  # constant markup, nothing user-supplied
    return ""


@register.filter
def code_label(value):
    """PAYMENT_CONFIRMED -> Payment confirmed (for raw status codes in reports)."""
    text = str(value).replace("_", " ").strip().lower()
    return text[:1].upper() + text[1:]
