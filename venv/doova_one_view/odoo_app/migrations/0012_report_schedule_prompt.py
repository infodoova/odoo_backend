from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('odoo_app', '0011_report_schedule'),
    ]

    operations = [
        migrations.AddField(
            model_name='reportschedule',
            name='prompt',
            field=models.TextField(blank=True, default=''),
        ),
    ]
