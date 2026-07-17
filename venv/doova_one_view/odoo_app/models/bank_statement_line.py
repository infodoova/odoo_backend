from django.db import models


class BankStatementLine(models.Model):
    """Bank statement line items from account.bank.statement.line"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='bank_statement_lines')
    company = models.ForeignKey('odoo_app.Company', on_delete=models.SET_NULL, null=True, blank=True)

    odoo_id = models.IntegerField()
    statement = models.ForeignKey('odoo_app.BankStatement', on_delete=models.CASCADE, related_name='lines')

    date = models.DateField(null=True, blank=True)
    date_dimension = models.ForeignKey('odoo_app.TimeDimension', on_delete=models.SET_NULL, null=True, blank=True, related_name='bank_statement_lines', db_column='date_id')

    name = models.CharField(max_length=500, null=True, blank=True)
    amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    partner = models.ForeignKey('odoo_app.Partner', on_delete=models.SET_NULL, null=True, blank=True, related_name='bank_statement_lines')

    ref = models.CharField(max_length=255, null=True, blank=True)

    odoo_write_date = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'fact_bank_statement_lines'
        unique_together = [['tenant', 'odoo_id']]
        indexes = [
            models.Index(fields=['tenant', 'date']),
            models.Index(fields=['amount']),
        ]

    def __str__(self):
        return f"{self.name} ({self.amount})"
