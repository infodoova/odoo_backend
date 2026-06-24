from django.db import models
import uuid


class AlertSchedule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # null tenant = system-wide schedule (runs for every tenant)
    tenant = models.ForeignKey(
        'odoo_app.Tenant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='alert_schedules',
    )

    name = models.CharField(max_length=200, default='Daily Activity Alert')
    prompt = models.TextField(default='', blank=True)
    recipients = models.JSONField()                  # ["admin@co.com"]
    companies = models.JSONField(default=list)        # [] = all, [1, 3] = specific
    timezone = models.CharField(max_length=60, default='UTC')
    is_enabled = models.BooleanField(default=True)
    is_system_default = models.BooleanField(default=False)  # True = runs for all tenants

    next_check_at = models.DateTimeField()
    last_checked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'alert_schedules'
        indexes = [
            models.Index(fields=['tenant', 'is_enabled']),
            models.Index(fields=['next_check_at']),
            models.Index(fields=['is_system_default']),
        ]

    def __str__(self):
        scope = 'System-wide' if self.is_system_default else (self.tenant.name if self.tenant else 'Unknown')
        return f"{self.name} — {scope}"


class AlertLog(models.Model):
    STATUS_CHOICES = [
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    id = models.BigAutoField(primary_key=True)
    schedule = models.ForeignKey(
        AlertSchedule,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='logs',
    )
    # denormalised so instant (schedule-less) runs are also queryable by tenant
    tenant = models.ForeignKey(
        'odoo_app.Tenant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='alert_logs',
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    has_anomalies = models.BooleanField(default=False)
    summary = models.TextField(null=True, blank=True)   # AI-generated brief
    alert_sent = models.BooleanField(default=False)
    error_message = models.TextField(null=True, blank=True)
    checked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'alert_logs'
        indexes = [
            models.Index(fields=['schedule', 'checked_at']),
            models.Index(fields=['tenant', 'checked_at']),
        ]
