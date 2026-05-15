from django.db import models


class SalesOrderLine(models.Model):
    """Sales order lines from sale.order.line"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='sales_order_lines')
    sales_order = models.ForeignKey('odoo_app.SalesOrder', on_delete=models.CASCADE, related_name='lines')

    odoo_id = models.IntegerField()
    odoo_order_id = models.IntegerField()

    product = models.ForeignKey('odoo_app.Product', on_delete=models.SET_NULL, null=True, blank=True, related_name='sales_lines')
    company = models.ForeignKey('odoo_app.Company', on_delete=models.SET_NULL, null=True, blank=True)

    product_uom_qty = models.DecimalField(max_digits=15, decimal_places=4)
    qty_delivered = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    qty_invoiced = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    price_unit = models.DecimalField(max_digits=15, decimal_places=2)
    price_subtotal = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    price_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    margin = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    purchase_price = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    odoo_write_date = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'fact_sales_order_lines'
        unique_together = [['tenant', 'odoo_id']]
        indexes = [
            models.Index(fields=['tenant', 'product']),
            models.Index(fields=['sales_order']),
        ]
