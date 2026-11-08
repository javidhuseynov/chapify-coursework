from django.contrib import admin
from django.urls import include, path

from printing import api_auth
from printing.api_docs import ApiDocsView, ApiSchemaView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/token/", api_auth.obtain_token, name="api_token_auth"),
    path("api/auth/token/revoke/", api_auth.revoke_current_token, name="api_token_revoke"),
    path("api/auth/tokens/", api_auth.list_tokens, name="api_token_list"),
    path("api/auth/tokens/<int:token_id>/", api_auth.delete_token, name="api_token_delete"),
    path("api/schema/", ApiSchemaView.as_view(), name="api_schema"),
    path("api/docs/", ApiDocsView.as_view(url_name="api_schema"), name="api_docs"),
    # Simulated external payment gateway (would be a third-party site in production).
    path("mock-gateway/", include("mockgateway.urls")),
    path("", include("printing.urls")),
]
