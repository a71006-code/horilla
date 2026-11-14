from django.conf import settings
from django.db import migrations, models
from django.db.models.deletion import PROTECT


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0009_recordedcaliforniapaycheck_recorded_by"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RecordedCaliforniaTaxDeposit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("federal_941", "IRS Form 941"), ("ca_de9", "California DE 9")], max_length=16)),
                ("period_start", models.DateField()),
                ("deposited_on", models.DateField()),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14)),
                ("reference", models.CharField(max_length=80)),
                ("recorded_at", models.DateTimeField(auto_now_add=True)),
                ("voided_at", models.DateTimeField(blank=True, null=True)),
                ("void_reason", models.CharField(blank=True, max_length=200)),
                ("employer", models.ForeignKey(on_delete=PROTECT, to="base.company")),
                ("recorded_by", models.ForeignKey(on_delete=PROTECT, to=settings.AUTH_USER_MODEL)),
                ("voided_by", models.ForeignKey(blank=True, null=True, on_delete=PROTECT, related_name="voided_california_deposits", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(condition=models.Q(("voided_at__isnull", True)), fields=("employer", "kind", "reference"), name="payroll_ca_deposit_ref_uniq"),
                    models.CheckConstraint(check=models.Q(("amount__gt", 0)), name="payroll_ca_deposit_positive"),
                ],
                "indexes": [models.Index(fields=["employer", "period_start"], name="payroll_ca_deposit_period_idx")],
            },
        ),
    ]
