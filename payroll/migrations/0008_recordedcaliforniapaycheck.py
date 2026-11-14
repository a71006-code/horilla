import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("payroll", "0007_alter_deduction_tax_reporting_type")]

    operations = [
        migrations.CreateModel(
            name="RecordedCaliforniaPaycheck",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("work_period_start", models.DateField()),
                ("work_period_end", models.DateField()),
                ("paid_on", models.DateField()),
                ("facts_version", models.PositiveSmallIntegerField(default=1)),
                ("facts", models.JSONField()),
                ("recorded_at", models.DateTimeField(auto_now_add=True)),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="employee.employee")),
                ("employer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="base.company")),
                ("payslip", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, to="payroll.payslip")),
            ],
            options={
                "indexes": [models.Index(fields=["employer", "paid_on"], name="payroll_ca_employer_paid_idx")],
            },
        ),
    ]
