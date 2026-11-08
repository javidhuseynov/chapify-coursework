from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Chapify Pay - merchant dashboard (test mode)"
admin.site.site_title = "Chapify Pay"

urlpatterns = [
    path("dashboard/", admin.site.urls),
    path("", include("checkout.urls")),
]
