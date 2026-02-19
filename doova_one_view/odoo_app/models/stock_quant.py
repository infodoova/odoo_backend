from django.db import models


class StockQuant(models.Model):
    """Current inventory levels from stock.quant"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='stock_quants')
    odoo_id = models.IntegerField()

    product = models.ForeignKey('odoo_app.Product', on_delete=models.SET_NULL, null=True, blank=True, related_name='quants')
    lot = models.ForeignKey('odoo_app.Lot', on_delete=models.SET_NULL, null=True, blank=True, related_name='quants')
    company = models.ForeignKey('odoo_app.Company', on_delete=models.SET_NULL, null=True, blank=True)

    location_name = models.CharField(max_length=255, null=True, blank=True)

    quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    reserved_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)

    in_date = models.DateTimeField(null=True, blank=True)

    odoo_write_date = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'fact_stock_quants'
        unique_together = [['tenant', 'odoo_id']]
        indexes = [
            models.Index(fields=['tenant', 'product']),
        ]

    @property
    def available_quantity(self):
        return self.quantity - self.reserved_quantity
