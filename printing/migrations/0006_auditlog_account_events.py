from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("printing", "0005_document_page_count"),
    ]

    operations = [
        migrations.AlterField(
            model_name="auditlog",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("LOGIN_SUCCESS", "Login success"),
                    ("LOGIN_FAILED", "Login failed"),
                    ("LOGOUT", "Logout"),
                    ("ACCOUNT_REGISTERED", "Account registered"),
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
