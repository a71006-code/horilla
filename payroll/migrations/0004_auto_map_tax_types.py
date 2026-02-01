from django.db import migrations, models

def map_tax_types(apps, schema_editor):
    Deduction = apps.get_model('payroll', 'Deduction')
    
    # Map specific types
    mapping = {
        'TDS': 'tds',
        'Provident Fund': '80c',
        'Professional Tax': 'professional_tax',
        'Health Insurance': '80d',
    }
    
    updated_count = 0
    for name, code in mapping.items():
        # Case-insensitive match
        rows = Deduction.objects.filter(name__iexact=name).update(tax_reporting_type=code)
        updated_count += rows
        print(f"Mapped {name} -> {code}: {rows} rows")
        
    # Set default 'other' for everything else that is still null
    # (Since we manually added the column without default, they are all NULL initially)
    remainder = Deduction.objects.filter(tax_reporting_type__isnull=True).update(tax_reporting_type='other')
    print(f"Set remaining {remainder} rows to 'other'")

class Migration(migrations.Migration):

    dependencies = [
        ('payroll', '0003_remove_historicalpayslip_tax_reporting_type_and_more'),
    ]

    operations = [
        # Inform Django the field exists (so apps.get_model sees it)
        # But do NOT touch the database (since we manually added the column)
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='deduction',
                    name='tax_reporting_type',
                    field=models.CharField(
                        blank=True,
                        choices=[('80c', '80C'), ('80d', '80D'), ('professional_tax', 'Professional Tax'), ('tds', 'TDS'), ('other', 'Other')],
                        default='other',
                        help_text='Select the tax reporting category for this deduction',
                        max_length=20
                    ),
                ),
            ],
            database_operations=[], 
        ),
        # Now run the data migration
        migrations.RunPython(map_tax_types, migrations.RunPython.noop),
    ]
