import uuid

from django.conf import settings
from django.db import migrations


def populate(apps, schema_editor):
    PaymentTransaction = apps.get_model("printing", "PaymentTransaction")
    Profile = apps.get_model("printing", "Profile")
    Printer = apps.get_model("printing", "Printer")
    User = apps.get_model(settings.AUTH_USER_MODEL)

    # Every existing payment gets its own unique reference.
    for payment in PaymentTransaction.objects.filter(reference__isnull=True):
        payment.reference = uuid.uuid4()
        payment.save(update_fields=["reference"])

    # Every existing user gets a profile. Existing superusers/staff become
    # Chapify administrators, everyone else is a normal user.
    for user in User.objects.all():
        if not Profile.objects.filter(user=user).exists():
            role = "ADMIN" if (user.is_superuser or user.is_staff) else "USER"
            Profile.objects.create(user=user, role=role, account_status="ACTIVE")

    # The print simulator needs at least one printer resource.
    if not Printer.objects.exists():
        Printer.objects.create(
            printer_name="Library Printer 1",
            location="Library / Study Center",
            printer_status="AVAILABLE",
        )


class Migration(migrations.Migration):

    dependencies = [
        ("printing", "0002_payment_attempts_and_job_details"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(populate, migrations.RunPython.noop),
    ]
