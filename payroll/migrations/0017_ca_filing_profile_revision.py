import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def capture_current_profiles(apps, schema_editor):
    profiles = apps.get_model("payroll", "CaliforniaEmployerFilingProfile")
    revisions = apps.get_model("payroll", "CaliforniaFilingProfileRevision")
    database = schema_editor.connection.alias
    for profile in profiles.objects.using(database).iterator():
        revisions.objects.using(database).create(
            profile_id=profile.pk, reviewed_at=profile.reviewed_at, reviewed_by_id=profile.reviewed_by_id,
            legal_name=profile.legal_name, ein=profile.ein, edd_account=profile.edd_account,
            federal_return=profile.federal_return,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0016_ca_reviewed_report"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="CaliforniaFilingProfileRevision",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("legal_name", models.CharField(max_length=160)),
                ("ein", models.CharField(max_length=9)),
                ("edd_account", models.CharField(max_length=8)),
                ("federal_return", models.CharField(max_length=3)),
                ("reviewed_at", models.DateTimeField()),
                ("profile", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="revisions", to="payroll.californiaemployerfilingprofile")),
                ("reviewed_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("profile", "reviewed_at"), name="payroll_ca_profile_revision_unique"),
                ],
            },
        ),
        migrations.RunPython(capture_current_profiles, migrations.RunPython.noop),
    ]
