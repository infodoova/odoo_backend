import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('odoo_app', '0012_report_schedule_prompt'),
    ]

    operations = [
        migrations.CreateModel(
            name='AlertSchedule',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(default='Daily Activity Alert', max_length=200)),
                ('prompt', models.TextField(blank=True, default='')),
                ('recipients', models.JSONField()),
                ('companies', models.JSONField(default=list)),
                ('timezone', models.CharField(default='UTC', max_length=60)),
                ('is_enabled', models.BooleanField(default=True)),
                ('is_system_default', models.BooleanField(default=False)),
                ('next_check_at', models.DateTimeField()),
                ('last_checked_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('tenant', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='alert_schedules',
                    to='odoo_app.tenant',
                )),
            ],
            options={
                'db_table': 'alert_schedules',
            },
        ),
        migrations.CreateModel(
            name='AlertLog',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('status', models.CharField(choices=[('completed', 'Completed'), ('failed', 'Failed')], max_length=10)),
                ('has_anomalies', models.BooleanField(default=False)),
                ('summary', models.TextField(blank=True, null=True)),
                ('alert_sent', models.BooleanField(default=False)),
                ('error_message', models.TextField(blank=True, null=True)),
                ('checked_at', models.DateTimeField(auto_now_add=True)),
                ('schedule', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='logs',
                    to='odoo_app.alertschedule',
                )),
                ('tenant', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='alert_logs',
                    to='odoo_app.tenant',
                )),
            ],
            options={
                'db_table': 'alert_logs',
            },
        ),
        migrations.AddIndex(
            model_name='alertschedule',
            index=models.Index(fields=['tenant', 'is_enabled'], name='alert_sched_tenant_enabled_idx'),
        ),
        migrations.AddIndex(
            model_name='alertschedule',
            index=models.Index(fields=['next_check_at'], name='alert_sched_next_check_idx'),
        ),
        migrations.AddIndex(
            model_name='alertschedule',
            index=models.Index(fields=['is_system_default'], name='alert_sched_sys_default_idx'),
        ),
        migrations.AddIndex(
            model_name='alertlog',
            index=models.Index(fields=['schedule', 'checked_at'], name='alert_log_schedule_idx'),
        ),
        migrations.AddIndex(
            model_name='alertlog',
            index=models.Index(fields=['tenant', 'checked_at'], name='alert_log_tenant_idx'),
        ),
    ]
