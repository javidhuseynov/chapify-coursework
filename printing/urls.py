from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("register/", views.register, name="register"),
    path("login/", views.ChapifyLoginView.as_view(), name="login"),
    path("logout/", views.ChapifyLogoutView.as_view(), name="logout"),
    path("upload/", views.upload_document, name="upload_document"),
    path("settings/<int:document_id>/", views.print_settings, name="print_settings"),
    path("payment/<int:request_id>/", views.payment, name="payment"),
    path("status/<int:request_id>/", views.request_status, name="request_status"),
    path("history/", views.request_history, name="request_history"),
    path("admin-dashboard/", views.admin_dashboard, name="admin_dashboard"),
]