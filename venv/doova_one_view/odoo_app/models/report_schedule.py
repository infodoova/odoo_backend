from django.db import models
import uuid


class ReportSchedule(models.Model):
    FREQUENCY_CHOICES = [
        ('daily',       'Daily'),
        ('weekly',      'Weekly'),
        ('biweekly',    'Every 2 Weeks'),
        ('monthly',     'Monthly'),
        ('quarterly',   'Every 3 Months'),
        ('semi_annual', 'Every 6 Months'),
        ('annual',      'Annually'),
    ]

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant       = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, null=True, blank=True, related_name='report_schedules')
    recipients   = models.JSONField()           # ["a@x.com", "b@x.com"]
    frequency    = models.CharField(max_length=20, choices=FREQUENCY_CHOICES)
    timezone     = models.CharField(max_length=60, default='UTC')
    companies    = models.JSONField(default=list)  # [] = all, [1, 3] = specific company IDs
    tenants      = models.JSONField(default=list)  # [] = creator tenant, ["uuid1", "uuid2"] = specific tenant IDs
    report_type  = models.CharField(max_length=30, default='analysis')
    prompt       = models.TextField(default='', blank=True)
    is_enabled   = models.BooleanField(default=True)
    next_send_at = models.DateTimeField()
    last_sent_at = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'report_schedules'
        indexes = [
            models.Index(fields=['tenant', 'is_enabled']),
            models.Index(fields=['next_send_at']),
        ]

    def __str__(self):
        return f"{self.tenant.name} — {self.frequency}"


class ReportLog(models.Model):
    STATUS_CHOICES = [
        ('sent',   'Sent'),
        ('failed', 'Failed'),
    ]

    id            = models.BigAutoField(primary_key=True)
    schedule      = models.ForeignKey(ReportSchedule, on_delete=models.CASCADE, related_name='logs')
    status        = models.CharField(max_length=10, choices=STATUS_CHOICES)
    filename      = models.CharField(max_length=255, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    sent_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'report_logs'
        indexes = [
            models.Index(fields=['schedule', 'sent_at']),
        ]
