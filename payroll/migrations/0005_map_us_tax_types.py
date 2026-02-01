from django.db import migrations, models

def map_us_tax_types(apps, schema_editor):
    Deduction = apps.get_model('payroll', 'Deduction')
    
    # Define US Mappings (Title Pattern -> Code)
    # Order matters? Specific before general.
    us_mapping = {
        'social security': 'FICA_SS',
        'medicare': 'FICA_MED',
        'futa': 'FUTA',
        'federal unemployment': 'FUTA',
        'federal tax': 'FIT',
        'ca tax': 'CA_PIT',
        'california state': 'CA_PIT',
        'sdi': 'CA_SDI',
        'disability': 'CA_SDI',
        'ui': 'CA_UI',
        'unemployment': 'CA_UI',
        'ett': 'CA_ETT',
        'training tax': 'CA_ETT',
    }
    
    # Iterate all deductions and check for matches
    # We only update if it's currently 'other' or NULL (though 0004 set them to 'other')
    # Or should we checking names aggressively? Yes, rely on name.
    
    # Iterate all deductions and check for matches
    for deduction in Deduction.objects.all():
        title = deduction.title.lower() # Use 'title' as confirmed in models.py
        
        # Check against US mapping
        for key, code in us_mapping.items():
            if key in title:
                deduction.tax_reporting_type = code
                deduction.save()
                print(f"Mapped '{deduction.title}' -> {code}")
                break

class Migration(migrations.Migration):

    dependencies = [
        ('payroll', '0004_auto_map_tax_types'),
    ]

    operations = [
        # Update Choices to include US and Indian Tax Types (Union)
        migrations.AlterField(
            model_name='deduction',
            name='tax_reporting_type',
            field=models.CharField(
                blank=True,
                choices=[
                    ('80c', '80C'), 
                    ('80d', '80D'), 
                    ('professional_tax', 'Professional Tax'), 
                    ('tds', 'TDS'), 
                    ('other', 'Other'),
                    ('FICA_SS', 'Social Security'),
                    ('FICA_MED', 'Medicare'),
                    ('FUTA', 'FUTA'),
                    ('FIT', 'Federal Income Tax'),
                    ('CA_PIT', 'CA PIT'),
                    ('CA_SDI', 'CA SDI'),
                    ('CA_UI', 'CA UI'),
                    ('CA_ETT', 'CA ETT'),
                ],
                default='other',
                help_text='Select the tax reporting category for this deduction',
                max_length=20
            ),
        ),
        migrations.RunPython(map_us_tax_types, migrations.RunPython.noop),
    ]
