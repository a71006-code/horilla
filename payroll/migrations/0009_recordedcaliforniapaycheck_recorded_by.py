from django.conf import settings
from django.db import migrations, models
from django.db.models.deletion import PROTECT


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0008_recordedcaliforniapaycheck"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="recordedcaliforniapaycheck", name="recorded_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=PROTECT, to=settings.AUTH_USER_MODEL),
        ),
    ]
