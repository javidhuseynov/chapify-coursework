from django.contrib import admin
from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/token/", obtain_auth_token, name="api_token_auth"),
    # Simulated external payment gateway (would be a third-party site in production).
    path("mock-gateway/", include("mockgateway.urls")),
    path("", include("printing.urls")),
]