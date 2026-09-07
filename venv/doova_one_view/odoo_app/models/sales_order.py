from django.db import models


class SalesOrder(models.Model):
    """Sales orders from sale.order"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='sales_orders')
    company = models.ForeignKey('odoo_app.Company', on_delete=models.SET_NULL, null=True, blank=True)

    odoo_id = models.IntegerField()
    odoo_name = models.CharField(max_length=100, null=True, blank=True)

    partner = models.ForeignKey('odoo_app.Partner', on_delete=models.SET_NULL, null=True, blank=True, related_name='sales_orders')
    user = models.ForeignKey('odoo_app.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='sales_orders')
    date_order_dimension = models.ForeignKey('odoo_app.TimeDimension', on_delete=models.SET_NULL, null=True, blank=True, db_column='date_order_id')

    date_order = models.DateTimeField()
    validity_date = models.DateField(null=True, blank=True)
    commitment_date = models.DateField(null=True, blank=True)

    STATE_CHOICES = [
        ('draft', 'Quotation'),
        ('sent', 'Quotation Sent'),
        ('sale', 'Sales Order'),
        ('done', 'Locked'),
        ('cancel', 'Cancelled'),
    ]
    state = models.CharField(max_length=50, choices=STATE_CHOICES)

    INVOICE_STATUS_CHOICES = [
        ('to invoice', 'To Invoice'),
        ('invoiced', 'Fully Invoiced'),
        ('no', 'Nothing to Invoice'),
    ]
    invoice_status = models.CharField(max_length=50, choices=INVOICE_STATUS_CHOICES, null=True, blank=True)

    amount_untaxed = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    amount_tax = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    amount_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    margin = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    currency_code = models.CharField(max_length=10, null=True, blank=True)

    odoo_create_date = models.DateTimeField(null=True, blank=True)
    odoo_write_date = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'fact_sales_orders'
        unique_together = [['tenant', 'odoo_id']]
        indexes = [
            models.Index(fields=['tenant', 'state']),
            models.Index(fields=['date_order']),
            models.Index(fields=['partner']),
        ]

    def __str__(self):
        return f"{self.odoo_name} - {self.partner.name if self.partner else 'No Partner'}"
