from django.contrib import admin
from django.urls import include, path

from printing import api_auth, printer_api
from printing.api_docs import ApiDocsView, ApiSchemaView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/token/", api_auth.obtain_token, name="api_token_auth"),
    path("api/auth/token/revoke/", api_auth.revoke_current_token, name="api_token_revoke"),
    path("api/auth/tokens/", api_auth.list_tokens, name="api_token_list"),
    path("api/auth/tokens/<int:token_id>/", api_auth.delete_token, name="api_token_delete"),
    path("api/printer/heartbeat/", printer_api.heartbeat, name="printer_api_heartbeat"),
    path("api/printer/jobs/next/", printer_api.next_job, name="printer_api_next_job"),
    path("api/printer/jobs/<int:job_id>/document/", printer_api.job_document, name="printer_api_document"),
    path("api/printer/jobs/<int:job_id>/complete/", printer_api.complete_job, name="printer_api_complete"),
    path("api/printer/jobs/<int:job_id>/fail/", printer_api.fail_job, name="printer_api_fail"),
    path("api/schema/", ApiSchemaView.as_view(), name="api_schema"),
    path("api/docs/", ApiDocsView.as_view(url_name="api_schema"), name="api_docs"),
    path("", include("printing.urls")),
]
