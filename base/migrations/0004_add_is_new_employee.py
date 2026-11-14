from django.db import migrations, models


def add_employee_flag(apps, schema_editor):
    user = apps.get_model("auth", "User")
    with schema_editor.connection.cursor() as cursor:
        columns = schema_editor.connection.introspection.get_table_description(cursor, user._meta.db_table)
    if any(column.name == "is_new_employee" for column in columns):
        return
    field = models.BooleanField(default=False)
    field.set_attributes_from_name("is_new_employee")
    field.model = user
    schema_editor.add_field(user, field)

class Migration(migrations.Migration):

    dependencies = [
        ('base', '0002_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(add_employee_flag, migrations.RunPython.noop),
    ]
