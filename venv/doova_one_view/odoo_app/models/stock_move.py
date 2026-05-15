from django.db import models


class StockMove(models.Model):
    """Stock moves from stock.move"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='stock_moves')
    picking = models.ForeignKey('odoo_app.StockPicking', on_delete=models.CASCADE, null=True, blank=True, related_name='moves')

    odoo_id = models.IntegerField()
    odoo_picking_id = models.IntegerField(null=True, blank=True)

    product = models.ForeignKey('odoo_app.Product', on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_moves')
    company = models.ForeignKey('odoo_app.Company', on_delete=models.SET_NULL, null=True, blank=True)
    date_dimension = models.ForeignKey('odoo_app.TimeDimension', on_delete=models.SET_NULL, null=True, blank=True, db_column='date_id')

    location_src = models.CharField(max_length=255, null=True, blank=True)
    location_dest = models.CharField(max_length=255, null=True, blank=True)

    product_uom_qty = models.DecimalField(max_digits=15, decimal_places=4)
    quantity_done = models.DecimalField(max_digits=15, decimal_places=4, default=0)

    date = models.DateTimeField(null=True, blank=True)
    date_deadline = models.DateField(null=True, blank=True)

    STATE_CHOICES = [
        ('draft', 'New'),
        ('waiting', 'Waiting Another Move'),
        ('confirmed', 'Waiting Availability'),
        ('assigned', 'Available'),
        ('done', 'Done'),
        ('cancel', 'Cancelled'),
    ]
    state = models.CharField(max_length=50, choices=STATE_CHOICES)

    origin = models.CharField(max_length=255, null=True, blank=True)
    reference = models.CharField(max_length=255, null=True, blank=True)
    name = models.TextField(null=True, blank=True)

    odoo_write_date = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'fact_stock_moves'
        unique_together = [['tenant', 'odoo_id']]
        indexes = [
            models.Index(fields=['tenant', 'product']),
            models.Index(fields=['date']),
        ]
