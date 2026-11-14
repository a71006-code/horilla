import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0014_ca_filed_quarter_totals"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CaliforniaFiledDe9c",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("profile_reviewed_at", models.DateTimeField()),
                ("period_start", models.DateField()),
                ("employee_rows", models.JSONField()),
                ("reviewed_at", models.DateTimeField(auto_now_add=True)),
                ("profile", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="payroll.californiaemployerfilingprofile")),
                ("reviewed_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["profile", "period_start", "profile_reviewed_at"],
                        name="payroll_ca_filed_de9c_idx",
                    ),
                ],
            },
        ),
    ]
