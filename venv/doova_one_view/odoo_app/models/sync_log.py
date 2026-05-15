from django.db import models


class SyncLog(models.Model):
    """Synchronization history and status"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='sync_logs')
    entity_type = models.CharField(max_length=100)

    SYNC_TYPE_CHOICES = [
        ('full', 'Full Sync'),
        ('delta', 'Delta Sync'),
    ]
    sync_type = models.CharField(max_length=50, choices=SYNC_TYPE_CHOICES)

    records_synced = models.IntegerField(default=0)
    records_failed = models.IntegerField(default=0)

    STATUS_CHOICES = [
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    status = models.CharField(max_length=50, choices=STATUS_CHOICES)
    error_message = models.TextField(null=True, blank=True)

    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'sync_logs'
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['entity_type']),
        ]
