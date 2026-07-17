from django.db import models


class BankStatement(models.Model):
    """Bank statement headers from account.bank.statement"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='bank_statements')
    company = models.ForeignKey('odoo_app.Company', on_delete=models.SET_NULL, null=True, blank=True)

    odoo_id = models.IntegerField()
    odoo_name = models.CharField(max_length=255, null=True, blank=True)

    date = models.DateField(null=True, blank=True)
    date_dimension = models.ForeignKey('odoo_app.TimeDimension', on_delete=models.SET_NULL, null=True, blank=True, related_name='bank_statements', db_column='date_id')

    journal = models.ForeignKey('odoo_app.AccountJournal', on_delete=models.SET_NULL, null=True, blank=True, related_name='bank_statements')
    journal_name = models.CharField(max_length=255, null=True, blank=True)
    currency_code = models.CharField(max_length=10, null=True, blank=True)

    balance_start = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    balance_end_real = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    STATE_CHOICES = [
        ('open', 'Open'),
        ('confirm', 'Confirmed'),
        ('posted', 'Posted'),
    ]
    state = models.CharField(max_length=50, choices=STATE_CHOICES, null=True, blank=True)

    odoo_write_date = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'fact_bank_statements'
        unique_together = [['tenant', 'odoo_id']]
        indexes = [
            models.Index(fields=['tenant', 'date']),
            models.Index(fields=['state']),
        ]

    def __str__(self):
        return f"{self.odoo_name} ({self.date})"
