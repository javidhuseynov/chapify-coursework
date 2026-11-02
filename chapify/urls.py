from django.contrib import admin
from django.urls import include, path

from printing.login_protection import ThrottledObtainAuthToken

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/token/", ThrottledObtainAuthToken.as_view(), name="api_token_auth"),
    # Simulated external payment gateway (would be a third-party site in production).
    path("mock-gateway/", include("mockgateway.urls")),
    path("", include("printing.urls")),
]