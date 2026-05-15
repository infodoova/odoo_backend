from django.db import models


class StockPicking(models.Model):
    """Stock pickings from stock.picking"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='stock_pickings')
    company = models.ForeignKey('odoo_app.Company', on_delete=models.SET_NULL, null=True, blank=True)

    odoo_id = models.IntegerField()
    odoo_name = models.CharField(max_length=100, null=True, blank=True)

    partner = models.ForeignKey('odoo_app.Partner', on_delete=models.SET_NULL, null=True, blank=True)
    scheduled_date_dimension = models.ForeignKey('odoo_app.TimeDimension', on_delete=models.SET_NULL, null=True, blank=True, related_name='pickings_scheduled', db_column='scheduled_date_id')
    date_done_dimension = models.ForeignKey('odoo_app.TimeDimension', on_delete=models.SET_NULL, null=True, blank=True, related_name='pickings_done', db_column='date_done_id')

    scheduled_date = models.DateTimeField(null=True, blank=True)
    date_done = models.DateTimeField(null=True, blank=True)

    PICKING_TYPE_CHOICES = [
        ('incoming', 'Receipt'),
        ('outgoing', 'Delivery'),
        ('internal', 'Internal Transfer'),
    ]
    picking_type = models.CharField(max_length=50, choices=PICKING_TYPE_CHOICES, null=True, blank=True)

    STATE_CHOICES = [
        ('draft', 'Draft'),
        ('waiting', 'Waiting Another Operation'),
        ('confirmed', 'Waiting'),
        ('assigned', 'Ready'),
        ('done', 'Done'),
        ('cancel', 'Cancelled'),
    ]
    state = models.CharField(max_length=50, choices=STATE_CHOICES)

    origin = models.CharField(max_length=255, null=True, blank=True)

    odoo_write_date = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'fact_stock_pickings'
        unique_together = [['tenant', 'odoo_id']]
