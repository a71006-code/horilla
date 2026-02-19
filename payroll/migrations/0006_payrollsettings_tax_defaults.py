from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payroll", "0005_map_us_tax_types"),
    ]

    operations = [
        migrations.AddField(
            model_name="payrollsettings",
            name="tax_designee_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="tax_designee_phone",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="tax_designee_pin",
            field=models.CharField(blank=True, max_length=5),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="tax_seasonal_employer",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="tax_signer_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="tax_signer_phone",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="tax_signer_title",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
