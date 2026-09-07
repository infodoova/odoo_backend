# Generated for full_reconcile_id support on AccountMoveLine

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('odoo_app', '0041_accountmove_odoo_create_date_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='accountmoveline',
            name='full_reconcile_id',
            field=models.IntegerField(blank=True, db_index=True, null=True),
        ),
    ]
