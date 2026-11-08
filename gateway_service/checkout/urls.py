from django.urls import path

from . import api, views

urlpatterns = [
    path("", views.index, name="index"),
    path("pay/<str:session_id>/", views.pay, name="pay"),
    path("pay/<str:session_id>/cancel/", views.cancel, name="cancel"),
    path("v1/checkout/sessions", api.create_session, name="api_create_session"),
    path("v1/checkout/sessions/<str:session_id>", api.get_session, name="api_get_session"),
]
