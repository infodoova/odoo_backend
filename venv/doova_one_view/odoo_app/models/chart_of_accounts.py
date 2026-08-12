from django.db import models


class ChartOfAccounts(models.Model):
    """
    Synced from Odoo's account.account model.
    Stores the full Chart of Accounts for each tenant, enabling
    auto-detection of account code prefixes for financial categorization.
    """
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey(
        'odoo_app.Tenant', on_delete=models.CASCADE, related_name='chart_of_accounts'
    )
    company = models.ForeignKey('odoo_app.Company', on_delete=models.SET_NULL, null=True, blank=True)
    odoo_id = models.IntegerField()
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    account_type = models.CharField(max_length=64, null=True, blank=True)
    reconcile = models.BooleanField(default=False)
    deprecated = models.BooleanField(default=False)

    odoo_write_date = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'dim_chart_of_accounts'
        unique_together = [['tenant', 'odoo_id']]

    def __str__(self):
        return f"{self.code} - {self.name}"
