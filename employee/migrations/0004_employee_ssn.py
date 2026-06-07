# Generated manually

import horilla.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('employee', '0003_alter_actiontype_action_type_alter_employee_dob_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='ssn',
            field=models.CharField(
                blank=True,
                help_text='Social Security Number used for US year-end payroll forms.',
                max_length=11,
                null=True,
                verbose_name='SSN',
            ),
        ),
    ]
