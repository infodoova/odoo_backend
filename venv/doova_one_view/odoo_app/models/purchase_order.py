from django.db import models


class PurchaseOrder(models.Model):
    """Purchase orders from purchase.order"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='purchase_orders')
    company = models.ForeignKey('odoo_app.Company', on_delete=models.SET_NULL, null=True, blank=True)

    odoo_id = models.IntegerField()
    odoo_name = models.CharField(max_length=100, null=True, blank=True)

    partner = models.ForeignKey('odoo_app.Partner', on_delete=models.SET_NULL, null=True, blank=True, related_name='purchase_orders')
    user = models.ForeignKey('odoo_app.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='purchase_orders')
    date_order_dimension = models.ForeignKey('odoo_app.TimeDimension', on_delete=models.SET_NULL, null=True, blank=True, db_column='date_order_id')

    date_order = models.DateTimeField()
    date_planned = models.DateTimeField(null=True, blank=True)
    date_approve = models.DateTimeField(null=True, blank=True)

    STATE_CHOICES = [
        ('draft', 'RFQ'),
        ('sent', 'RFQ Sent'),
        ('to approve', 'To Approve'),
        ('purchase', 'Purchase Order'),
        ('done', 'Locked'),
        ('cancel', 'Cancelled'),
    ]
    state = models.CharField(max_length=50, choices=STATE_CHOICES)

    INVOICE_STATUS_CHOICES = [
        ('no', 'Nothing to Bill'),
        ('to invoice', 'Waiting Bills'),
        ('invoiced', 'Fully Billed'),
    ]
    invoice_status = models.CharField(max_length=50, choices=INVOICE_STATUS_CHOICES, null=True, blank=True)

    amount_untaxed = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    amount_tax = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    amount_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    currency_code = models.CharField(max_length=10, null=True, blank=True)

    partner_ref = models.CharField(max_length=255, null=True, blank=True)

    odoo_write_date = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'fact_purchase_orders'
        unique_together = [['tenant', 'odoo_id']]
