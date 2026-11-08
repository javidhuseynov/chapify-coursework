"""Merchant API (server to server), authenticated with the merchant's secret key.

    POST /v1/checkout/sessions            create a checkout session
    GET  /v1/checkout/sessions/<id>       read its status and result
"""

import hmac
import json

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import services
from .models import CheckoutSession


def authenticated_merchant(request):
    merchant = settings.MERCHANT
    header = request.headers.get("Authorization", "")
    scheme, _, key = header.partition(" ")
    if scheme.lower() == "bearer" and key and hmac.compare_digest(key.strip(), merchant["api_key"]):
        return merchant
    return None


def error(message, status):
    return JsonResponse({"error": message}, status=status)


def base_url(request):
    return f"{request.scheme}://{request.get_host()}"


@csrf_exempt  # authenticated by the API key, not by a browser session
@require_POST
def create_session(request):
    merchant = authenticated_merchant(request)
    if merchant is None:
        return error("Invalid API key.", 401)

    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return error("The request body must be JSON.", 400)

    try:
        session, created = services.create_session(merchant, data)
    except services.GatewayError as problem:
        return error(str(problem), problem.status)

    return JsonResponse(services.session_json(session, base_url(request)), status=201 if created else 200)


@require_GET
def get_session(request, session_id):
    merchant = authenticated_merchant(request)
    if merchant is None:
        return error("Invalid API key.", 401)

    session = CheckoutSession.objects.filter(pk=session_id, merchant=merchant["id"]).first()
    if session is None:
        return error("No such checkout session.", 404)

    return JsonResponse(services.session_json(services.expire_if_due(session), base_url(request)))
