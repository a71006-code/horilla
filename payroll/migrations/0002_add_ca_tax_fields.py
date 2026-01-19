# Generated manually for CA State Tax fields

from django.db import migrations, models
import django.db.models.deletion
import payroll.models.models


class Migration(migrations.Migration):

    dependencies = [
        ('payroll', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='contract',
            name='ca_filing_status',
            field=models.ForeignKey(
                blank=True,
                help_text='California state tax filing status for Method B calculation',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='ca_contracts',
                to='payroll.filingstatus',
                verbose_name='CA Filing Status',
            ),
        ),
        migrations.AddField(
            model_name='contract',
            name='ca_allowances',
            field=models.IntegerField(
                default=0,
                help_text='Number of California state withholding allowances',
                validators=[payroll.models.models.min_zero],
                verbose_name='CA Allowances',
            ),
        ),
    ]
