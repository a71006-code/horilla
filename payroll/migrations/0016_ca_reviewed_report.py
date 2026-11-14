import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0015_ca_filed_de9c"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CaliforniaReviewedReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("period_start", models.DateField()),
                ("kind", models.CharField(choices=[("quarterly", "941, DE 9 and DE 9C"), ("futa", "Form 940"), ("wage_statements", "W-2 and W-3")], max_length=16)),
                ("digest", models.CharField(max_length=64)),
                ("source_records", models.JSONField()),
                ("csv_text", models.TextField()),
                ("reviewed_at", models.DateTimeField(auto_now_add=True)),
                ("employer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="base.company")),
                ("reviewed_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("employer", "period_start", "kind", "digest"), name="payroll_ca_reviewed_report_unique"),
                ],
            },
        ),
        migrations.CreateModel(
            name="CaliforniaFiledReportConfirmation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("form_code", models.CharField(max_length=4)),
                ("reference", models.CharField(max_length=80)),
                ("filed_on", models.DateField()),
                ("reviewed_at", models.DateTimeField(auto_now_add=True)),
                ("report", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="filing_confirmations", to="payroll.californiareviewedreport")),
                ("reviewed_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("report", "form_code", "reference"), name="payroll_ca_report_confirmation_unique"),
                ],
            },
        ),
    ]
