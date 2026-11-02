import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("printing", "0003_populate_references_and_profiles"),
    ]

    operations = [
        migrations.AlterField(
            model_name="paymenttransaction",
            name="reference",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        # One request may now have several payment attempts.
        migrations.AlterField(
            model_name="paymenttransaction",
            name="print_request",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="payments",
                to="printing.printrequest",
            ),
        ),
        # ...but never more than one confirmed payment.
        migrations.AddConstraint(
            model_name="paymenttransaction",
            constraint=models.UniqueConstraint(
                condition=models.Q(("payment_status", "CONFIRMED")),
                fields=("print_request",),
                name="unique_confirmed_payment_per_request",
            ),
        ),
    ]
