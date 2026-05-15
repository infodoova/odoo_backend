from django.db import models


class Lot(models.Model):
    """Lot/serial numbers with expiry tracking from stock.lot"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='lots')
    odoo_id = models.IntegerField()

    product = models.ForeignKey('odoo_app.Product', on_delete=models.SET_NULL, null=True, blank=True, related_name='lots')
    company = models.ForeignKey('odoo_app.Company', on_delete=models.SET_NULL, null=True, blank=True)

    name = models.CharField(max_length=255)
    ref = models.CharField(max_length=255, null=True, blank=True)

    expiration_date = models.DateField(null=True, blank=True)
    use_date = models.DateField(null=True, blank=True)
    removal_date = models.DateField(null=True, blank=True)
    alert_date = models.DateField(null=True, blank=True)

    odoo_write_date = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'dim_lots'
        unique_together = [['tenant', 'odoo_id']]
        indexes = [
            models.Index(fields=['expiration_date']),
            models.Index(fields=['product']),
        ]

    def __str__(self):
        return f"{self.name} - {self.product.name if self.product else 'No Product'}"
