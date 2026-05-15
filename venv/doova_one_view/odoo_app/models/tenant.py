from django.db import models
import uuid


class Tenant(models.Model):
    """Odoo instance configuration"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    odoo_url = models.URLField(max_length=500)
    odoo_database = models.CharField(max_length=100)
    api_key_encrypted = models.BinaryField()
    is_active = models.BooleanField(default=True)

    SYNC_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('syncing', 'Syncing'),
        ('active', 'Active'),
        ('error', 'Error'),
    ]
    sync_status = models.CharField(max_length=50, choices=SYNC_STATUS_CHOICES, default='pending')
    last_sync_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenants'

    def __str__(self):
        return self.name
