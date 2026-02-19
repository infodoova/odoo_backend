from django.db import models


class PurchaseOrderLine(models.Model):
    """Purchase order lines from purchase.order.line"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='purchase_order_lines')
    purchase_order = models.ForeignKey('odoo_app.PurchaseOrder', on_delete=models.CASCADE, related_name='lines')

    odoo_id = models.IntegerField()
    odoo_order_id = models.IntegerField()

    product = models.ForeignKey('odoo_app.Product', on_delete=models.SET_NULL, null=True, blank=True, related_name='purchase_lines')
    company = models.ForeignKey('odoo_app.Company', on_delete=models.SET_NULL, null=True, blank=True)

    product_qty = models.DecimalField(max_digits=15, decimal_places=4)
    qty_received = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    qty_invoiced = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    price_unit = models.DecimalField(max_digits=15, decimal_places=2)
    price_subtotal = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    price_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    date_planned = models.DateTimeField(null=True, blank=True)

    name = models.TextField(null=True, blank=True)
    odoo_write_date = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'fact_purchase_order_lines'
        unique_together = [['tenant', 'odoo_id']]
