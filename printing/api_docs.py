"""OpenAPI schema and interactive API documentation (Swagger UI).

Both require a logged-in user. Swagger UI is served from Chapify's own static
files (drf-spectacular-sidecar) and its start-up script is a separate file,
so the page works under Chapify's Content-Security-Policy (no CDN, no inline
scripts or styles).
"""

from django.contrib.auth.views import redirect_to_login
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from drf_spectacular.utils import extend_schema
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerSplitView


class ApiSchemaView(SpectacularAPIView):
    pass


class ApiDocsView(SpectacularSwaggerSplitView):
    template_name = "printing/api_docs.html"

    def check_permissions(self, request):
        # Visitors who are not logged in are sent to the login page (see get).
        if request.user.is_authenticated or request.GET.get("script") is not None:
            super().check_permissions(request)

    @extend_schema(exclude=True)
    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        return super().get(request, *args, **kwargs)


class ExpiringTokenScheme(OpenApiAuthenticationExtension):
    """Describes printing.api_tokens.ExpiringTokenAuthentication in the schema."""

    target_class = "printing.api_tokens.ExpiringTokenAuthentication"
    name = "tokenAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": "Value: 'Token <token>' (token from POST /api/auth/token/).",
        }
