"""Security middleware that Django does not provide out of the box."""

from django.conf import settings
from django.http import HttpResponse


class RequestSizeLimitMiddleware:
    """Reject request bodies larger than MAX_REQUEST_BODY_BYTES with HTTP 413.

    Django limits form fields (DATA_UPLOAD_MAX_MEMORY_SIZE) but streams file
    uploads of any size to disk before the form can reject them. Checking the
    declared Content-Length first stops huge uploads before they are read.
    (A production web server such as nginx should enforce the same limit.)
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            length = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0

        if length > settings.MAX_REQUEST_BODY_BYTES:
            return HttpResponse(
                "Request too large. Uploaded documents may be at most 5 MB.",
                status=413,
                content_type="text/plain; charset=utf-8",
            )

        return self.get_response(request)


class PermissionsPolicyMiddleware:
    """Tell browsers that Chapify never uses powerful device features."""

    POLICY = (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
        "bluetooth=(), serial=(), magnetometer=(), gyroscope=(), accelerometer=()"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Permissions-Policy", self.POLICY)
        return response
