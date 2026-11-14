import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0017_ca_filing_profile_revision"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.RemoveConstraint(
            model_name="californiafiledreportconfirmation",
            name="payroll_ca_report_confirmation_unique",
        ),
        migrations.CreateModel(
            name="CaliforniaFilingConfirmationVoid",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reason", models.CharField(max_length=200)),
                ("reviewed_at", models.DateTimeField(auto_now_add=True)),
                ("confirmation", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="void_record", to="payroll.californiafiledreportconfirmation")),
                ("reviewed_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={"abstract": False},
        ),
    ]
