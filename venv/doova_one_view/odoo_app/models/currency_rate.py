from django.db import models

class CurrencyRate(models.Model):
    """Daily exchange rates from Odoo res.currency.rate"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='currency_rates')
    currency = models.ForeignKey('odoo_app.Currency', on_delete=models.CASCADE, related_name='rates')
    company = models.ForeignKey('odoo_app.Company', on_delete=models.SET_NULL, null=True, blank=True)
    
    odoo_id = models.IntegerField()
    name = models.DateField(help_text="Date of the exchange rate")
    rate = models.DecimalField(max_digits=18, decimal_places=6, help_text="Exchange rate")
    
    odoo_write_date = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'dim_currency_rates'
        unique_together = [['tenant', 'odoo_id']]
        indexes = [
            models.Index(fields=['tenant', 'currency', 'name']),
        ]

    def __str__(self):
        return f"{self.currency.code} rate on {self.name}: {self.rate}"
