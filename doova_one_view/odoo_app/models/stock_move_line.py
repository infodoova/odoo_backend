from django.db import models


class StockMoveLine(models.Model):
    """Detailed stock move lines from stock.move.line"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='stock_move_lines')
    stock_move = models.ForeignKey('odoo_app.StockMove', on_delete=models.CASCADE, related_name='move_lines')

    odoo_id = models.IntegerField()
    odoo_move_id = models.IntegerField()

    product = models.ForeignKey('odoo_app.Product', on_delete=models.SET_NULL, null=True, blank=True)
    lot = models.ForeignKey('odoo_app.Lot', on_delete=models.SET_NULL, null=True, blank=True, related_name='move_lines')
    company = models.ForeignKey('odoo_app.Company', on_delete=models.SET_NULL, null=True, blank=True)

    location_src = models.CharField(max_length=255, null=True, blank=True)
    location_dest = models.CharField(max_length=255, null=True, blank=True)

    qty_done = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    product_uom_qty = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)

    date = models.DateTimeField(null=True, blank=True)
    state = models.CharField(max_length=50, null=True, blank=True)

    odoo_write_date = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'fact_stock_move_lines'
        unique_together = [['tenant', 'odoo_id']]
