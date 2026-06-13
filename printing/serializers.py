from rest_framework import serializers

from .models import (
    AuditLog,
    Document,
    PaymentTransaction,
    Printer,
    PrintJob,
    PrintRequest,
    PrintSettings,
)


class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = [
            "id",
            "file_name",
            "file_type",
            "file_size",
            "upload_time",
            "validation_status",
        ]


class PrintSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrintSettings
        fields = [
            "id",
            "copies",
            "color_mode",
            "paper_format",
            "duplex_mode",
        ]


class PrintRequestSerializer(serializers.ModelSerializer):
    document = DocumentSerializer(read_only=True)
    settings = PrintSettingsSerializer(read_only=True)

    class Meta:
        model = PrintRequest
        fields = [
            "id",
            "document",
            "settings",
            "status",
            "document_pages",
            "total_price",
            "created_at",
            "updated_at",
        ]


class PaymentTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentTransaction
        fields = [
            "id",
            "print_request",
            "amount",
            "payment_status",
            "payment_date",
            "gateway_reference",
        ]


class PrinterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Printer
        fields = [
            "id",
            "printer_name",
            "location",
            "printer_status",
        ]


class PrintJobSerializer(serializers.ModelSerializer):
    printer = PrinterSerializer(read_only=True)

    class Meta:
        model = PrintJob
        fields = [
            "id",
            "print_request",
            "printer",
            "job_status",
            "created_at",
            "completed_at",
        ]


class AuditLogSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "username",
            "print_request",
            "event_type",
            "event_timestamp",
            "description",
        ]