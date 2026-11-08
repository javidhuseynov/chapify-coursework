from django.contrib import admin

from .models import (
    Profile,
    Document,
    PrintSettings,
    PrintRequest,
    PaymentTransaction,
    Printer,
    PrintJob,
    AuditLog,
    ApiToken,
)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "account_status")
    list_filter = ("role", "account_status")
    search_fields = ("user__username", "user__email")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("file_name", "user", "file_type", "file_size", "validation_status", "upload_time")
    list_filter = ("validation_status", "file_type", "upload_time")
    search_fields = ("file_name", "user__username")


@admin.register(PrintSettings)
class PrintSettingsAdmin(admin.ModelAdmin):
    list_display = ("copies", "color_mode", "paper_format", "duplex_mode")
    list_filter = ("color_mode", "paper_format", "duplex_mode")


@admin.register(PrintRequest)
class PrintRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "status", "document_pages", "total_price", "created_at", "updated_at")
    list_filter = ("status", "created_at", "updated_at")
    search_fields = ("user__username", "document__file_name")


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ("reference", "print_request", "amount", "currency", "payment_status", "payment_date", "gateway_reference")
    list_filter = ("payment_status", "payment_date")
    search_fields = ("reference", "gateway_reference", "print_request__user__username")
    readonly_fields = ("reference",)


@admin.register(Printer)
class PrinterAdmin(admin.ModelAdmin):
    list_display = ("printer_name", "location", "printer_status")
    list_filter = ("printer_status", "location")
    search_fields = ("printer_name", "location")


@admin.register(PrintJob)
class PrintJobAdmin(admin.ModelAdmin):
    list_display = ("print_request", "printer", "job_status", "created_at", "started_at", "completed_at", "failure_reason")
    list_filter = ("job_status", "created_at", "completed_at")
    search_fields = ("print_request__user__username", "printer__printer_name")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("event_type", "user", "print_request", "event_timestamp")
    list_filter = ("event_type", "event_timestamp")
    search_fields = ("description", "user__username")

@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "key_prefix", "created_at", "expires_at", "last_used_at", "revoked_at")
    list_filter = ("revoked_at",)
    search_fields = ("user__username", "name", "key_prefix")
    # Tokens are created only through the API; only the hash is stored.
    readonly_fields = ("user", "name", "key_prefix", "key_hash", "created_at", "expires_at", "last_used_at")

    def has_add_permission(self, request):
        return False
