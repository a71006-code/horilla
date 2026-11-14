from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0013_ca_paid_check_edd_review"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CaliforniaFiledQuarterTotals",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("profile_reviewed_at", models.DateTimeField()),
                ("period_start", models.DateField()),
                ("amounts", models.JSONField()),
                ("reviewed_at", models.DateTimeField(auto_now_add=True)),
                ("profile", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="payroll.californiaemployerfilingprofile")),
                ("reviewed_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["profile", "profile_reviewed_at", "period_start"], name="payroll_ca_filed_quarter_idx"),
                ],
            },
        ),
    ]
