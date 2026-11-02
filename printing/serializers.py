from rest_framework import serializers
from .validators import DocumentValidationError, inspect_uploaded_document

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
            "page_count",
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
            "reference",
            "amount",
            "currency",
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
            "started_at",
            "completed_at",
            "failure_reason",
        ]


class AuditLogSerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()

    def get_username(self, obj):
        return obj.user.username if obj.user_id else None

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

class CreatePrintRequestSerializer(serializers.Serializer):
    """The page count is read from the uploaded PDF; any client-sent value is ignored."""

    file = serializers.FileField()
    copies = serializers.IntegerField(min_value=1)
    color_mode = serializers.ChoiceField(choices=PrintSettings.COLOR_CHOICES)
    paper_format = serializers.ChoiceField(choices=PrintSettings.PAPER_CHOICES)
    duplex_mode = serializers.ChoiceField(choices=PrintSettings.DUPLEX_CHOICES)

    def validate_file(self, uploaded_file):
        try:
            self.page_count = inspect_uploaded_document(uploaded_file)
        except DocumentValidationError as error:
            raise serializers.ValidationError(str(error))

        return uploaded_file