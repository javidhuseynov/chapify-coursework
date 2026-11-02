from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("printing", "0004_payment_constraints"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="page_count",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
