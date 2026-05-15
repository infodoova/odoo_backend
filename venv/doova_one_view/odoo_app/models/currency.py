from django.db import models


class Currency(models.Model):
    """Currency dimension from res.currency"""

    SYMBOL_POSITION_CHOICES = [
        ('before', 'Before Amount'),
        ('after', 'After Amount'),
    ]

    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey(
        'odoo_app.Tenant',
        on_delete=models.CASCADE,
        related_name='currencies'
    )
    odoo_id = models.IntegerField()
    code = models.CharField(max_length=10)
    symbol = models.CharField(max_length=10, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    symbol_position = models.CharField(
        max_length=10,
        choices=SYMBOL_POSITION_CHOICES,
        default='after'
    )
    rounding = models.DecimalField(max_digits=10, decimal_places=6, default=0.01)
    odoo_write_date = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'dim_currencies'
        unique_together = [['tenant', 'odoo_id']]
        indexes = [
            models.Index(fields=['tenant'], name='idx_currencies_tenant'),
            models.Index(fields=['tenant', 'code'], name='idx_currencies_code'),
            models.Index(fields=['tenant', 'is_active'], name='idx_currencies_active'),
        ]
        verbose_name_plural = 'Currencies'

    def __str__(self):
        return f"{self.code} ({self.symbol or '-'})"