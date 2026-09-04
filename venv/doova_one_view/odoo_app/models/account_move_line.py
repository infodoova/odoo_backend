from django.db import models


class AccountMoveLine(models.Model):
    """Account move lines from account.move.line"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='account_move_lines')
    account_move = models.ForeignKey('odoo_app.AccountMove', on_delete=models.CASCADE, related_name='lines')

    odoo_id = models.IntegerField()
    odoo_move_id = models.IntegerField()

    product = models.ForeignKey('odoo_app.Product', on_delete=models.SET_NULL, null=True, blank=True, related_name='account_lines')
    partner = models.ForeignKey('odoo_app.Partner', on_delete=models.SET_NULL, null=True, blank=True)
    company = models.ForeignKey('odoo_app.Company', on_delete=models.SET_NULL, null=True, blank=True)

    account_odoo_id = models.IntegerField(null=True, blank=True, db_index=True)
    account_code = models.CharField(max_length=50, null=True, blank=True)
    account_name = models.CharField(max_length=255, null=True, blank=True)
    account_type = models.CharField(max_length=50, null=True, blank=True)

    debit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    balance = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    amount_currency = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    currency_code = models.CharField(max_length=10, null=True, blank=True)

    quantity = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    price_unit = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    price_subtotal = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)

    name = models.TextField(null=True, blank=True)
    odoo_write_date = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'fact_account_move_lines'
        unique_together = [['tenant', 'odoo_id']]
