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
    path("api/my/requests/", views.api_my_requests, name="api_my_requests"),
    path("api/my/requests/<int:request_id>/", views.api_request_detail, name="api_request_detail"),
    path("api/my/payments/", views.api_my_payments, name="api_my_payments"),
    path("api/my/print-jobs/", views.api_my_print_jobs, name="api_my_print_jobs"),

    path("api/admin/summary/", views.api_admin_summary, name="api_admin_summary"),
    path("api/admin/requests/", views.api_admin_requests, name="api_admin_requests"),
    path("api/admin/transactions/", views.api_admin_transactions, name="api_admin_transactions"),
    path("api/admin/print-jobs/", views.api_admin_print_jobs, name="api_admin_print_jobs"),
    path("api/admin/printers/", views.api_admin_printers, name="api_admin_printers"),
    path("api/admin/audit-logs/", views.api_admin_audit_logs, name="api_admin_audit_logs"),
    path("api/requests/create/", views.api_create_print_request, name="api_create_print_request"),
    path("api/requests/<int:request_id>/payment/confirm/", views.api_confirm_payment, name="api_confirm_payment"),
    path("api/requests/<int:request_id>/payment/reject/", views.api_reject_payment, name="api_reject_payment"),
]