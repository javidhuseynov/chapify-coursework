from django.urls import path

from . import views

app_name = "mockgateway"

urlpatterns = [
    path("checkout/", views.checkout, name="checkout"),
]
