import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("printing", "0001_initial"),
    ]

    operations = [
        # Payment attempts: own reference (filled in 0003, made unique in 0004),
        # currency and last-update timestamp.
        migrations.AddField(
            model_name="paymenttransaction",
            name="reference",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name="paymenttransaction",
            name="currency",
            field=models.CharField(default="EUR", max_length=3),
        ),
        migrations.AddField(
            model_name="paymenttransaction",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        # Print job lifecycle details.
        migrations.AddField(
            model_name="printjob",
            name="started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="printjob",
            name="failure_reason",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        # Brings the audit event list in line with the model (the June 2026
        # models added DOCUMENT_DELETED and PRINT_REQUEST_CREATED without a
        # migration) and adds the new event types.
        migrations.AlterField(
            model_name="auditlog",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("LOGIN_SUCCESS", "Login success"),
                    ("LOGIN_FAILED", "Login failed"),
                    ("DOCUMENT_UPLOADED", "Document uploaded"),
                    ("DOCUMENT_VALIDATED", "Document validated"),
                    ("DOCUMENT_DELETED", "Document deleted from storage"),
                    ("PRINT_REQUEST_CREATED", "Print request created"),
                    ("PRINT_REQUEST_UPDATED", "Print request updated"),
                    ("PRINT_REQUEST_CANCELLED", "Print request cancelled"),
                    ("PAYMENT_INITIATED", "Payment initiated"),
                    ("PAYMENT_CONFIRMED", "Payment confirmed"),
                    ("PAYMENT_REJECTED", "Payment rejected"),
                    ("PAYMENT_NOTIFICATION_REFUSED", "Payment notification refused"),
                    ("PRINT_JOB_CREATED", "Print job created"),
                    ("PRINT_JOB_STATUS_CHANGED", "Print job status changed"),
                    ("USER_MANAGED", "User managed"),
                    ("ADMIN_ACTION", "Admin action"),
                ],
                max_length=40,
            ),
        ),
    ]
