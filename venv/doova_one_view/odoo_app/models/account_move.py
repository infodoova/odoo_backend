from django.db import models


class AccountMove(models.Model):
    """Invoices, bills, and journal entries from account.move"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='account_moves')
    company = models.ForeignKey('odoo_app.Company', on_delete=models.SET_NULL, null=True, blank=True)

    odoo_id = models.IntegerField()
    odoo_name = models.CharField(max_length=100, null=True, blank=True)

    partner = models.ForeignKey('odoo_app.Partner', on_delete=models.SET_NULL, null=True, blank=True, related_name='account_moves')
    journal = models.ForeignKey('odoo_app.AccountJournal', on_delete=models.SET_NULL, null=True, blank=True, related_name='account_moves')
    date_dimension = models.ForeignKey('odoo_app.TimeDimension', on_delete=models.SET_NULL, null=True, blank=True, related_name='moves_by_date', db_column='date_id')
    invoice_date_dimension = models.ForeignKey('odoo_app.TimeDimension', on_delete=models.SET_NULL, null=True, blank=True, related_name='moves_by_invoice_date', db_column='invoice_date_id')

    date = models.DateField()
    invoice_date = models.DateField(null=True, blank=True)
    invoice_date_due = models.DateField(null=True, blank=True)

    MOVE_TYPE_CHOICES = [
        ('out_invoice', 'Customer Invoice'),
        ('in_invoice', 'Vendor Bill'),
        ('out_refund', 'Customer Credit Note'),
        ('in_refund', 'Vendor Credit Note'),
        ('entry', 'Journal Entry'),
    ]
    move_type = models.CharField(max_length=50, choices=MOVE_TYPE_CHOICES)

    STATE_CHOICES = [
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancel', 'Cancelled'),
    ]
    state = models.CharField(max_length=50, choices=STATE_CHOICES)

    PAYMENT_STATE_CHOICES = [
        ('not_paid', 'Not Paid'),
        ('in_payment', 'In Payment'),
        ('paid', 'Paid'),
        ('partial', 'Partially Paid'),
        ('reversed', 'Reversed'),
    ]
    payment_state = models.CharField(max_length=50, choices=PAYMENT_STATE_CHOICES, null=True, blank=True)

    amount_untaxed = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    amount_tax = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    amount_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    amount_residual = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    amount_total_signed = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    amount_residual_signed = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    currency_code = models.CharField(max_length=10, null=True, blank=True)

    invoice_origin = models.CharField(max_length=255, null=True, blank=True)
    ref = models.CharField(max_length=255, null=True, blank=True)

    odoo_create_date = models.DateTimeField(null=True, blank=True)
    odoo_write_date = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'fact_account_moves'
        unique_together = [['tenant', 'odoo_id']]
        indexes = [
            models.Index(fields=['tenant', 'move_type']),
            models.Index(fields=['date']),
            models.Index(fields=['state']),
            models.Index(fields=['payment_state']),
        ]
