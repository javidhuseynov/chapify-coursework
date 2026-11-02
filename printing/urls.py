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
    path("payments/return/", views.payment_return, name="payment_return"),
    path("payments/callback/", views.payment_callback, name="payment_callback"),
    path("status/<int:request_id>/", views.request_status, name="request_status"),
    path("history/", views.request_history, name="request_history"),

    path("request/<int:request_id>/edit/", views.edit_print_request, name="edit_print_request"),
    path("request/<int:request_id>/cancel/", views.cancel_print_request, name="cancel_print_request"),

    path("admin-dashboard/", views.admin_dashboard, name="admin_dashboard"),
    path("admin-report/", views.admin_report, name="admin_report"),
    path("admin-dashboard/process-print-job/", views.admin_process_print_job, name="admin_process_print_job"),
    path("admin-dashboard/jobs/<int:job_id>/retry/", views.admin_retry_print_job, name="admin_retry_print_job"),
    path("admin-users/", views.admin_users, name="admin_users"),
    path("admin-users/<int:user_id>/action/", views.admin_user_action, name="admin_user_action"),
    path("admin-transactions/", views.admin_transactions, name="admin_transactions"),
    path("admin-printers/", views.admin_printers, name="admin_printers"),
    path("admin-printers/<int:printer_id>/status/", views.admin_printer_status, name="admin_printer_status"),

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
    path("api/requests/<int:request_id>/payment/", views.api_initiate_payment, name="api_initiate_payment"),
    path("api/requests/<int:request_id>/cancel/", views.api_cancel_print_request, name="api_cancel_print_request"),
]