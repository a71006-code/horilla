from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("payroll", "0010_recordedcaliforniataxdeposit")]
    operations = [
        migrations.AlterField(
            model_name="recordedcaliforniataxdeposit", name="kind",
            field=models.CharField(max_length=16, choices=[
                ("federal_941", "IRS Form 941"), ("ca_de9", "California DE 9"),
                ("federal_940", "IRS Form 940"),
            ]),
        ),
        migrations.AddConstraint(
            model_name="recordedcaliforniataxdeposit",
            constraint=models.UniqueConstraint(
                fields=("employer", "reference"),
                condition=models.Q(kind__in=("federal_941", "federal_940"), voided_at__isnull=True),
                name="payroll_ca_irs_ref_uniq",
            ),
        ),
    ]
