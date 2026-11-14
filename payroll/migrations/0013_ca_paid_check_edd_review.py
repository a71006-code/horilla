from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0012_ca_filing_review"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CaliforniaPaidCheckEddReview",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("subject_wages", models.DecimalField(decimal_places=2, max_digits=14)),
                ("plan_code", models.CharField(max_length=1)),
                ("reviewed_at", models.DateTimeField(auto_now_add=True)),
                ("paid_check", models.OneToOneField(db_column="check_id", on_delete=django.db.models.deletion.PROTECT, related_name="edd_review", to="payroll.recordedcaliforniapaycheck")),
                ("reviewed_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={"abstract": False},
        ),
    ]
