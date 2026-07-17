from django.db import models


class AccountJournal(models.Model):
    """Account journals from account.journal"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='account_journals')
    company = models.ForeignKey('odoo_app.Company', on_delete=models.SET_NULL, null=True, blank=True)

    odoo_id = models.IntegerField()
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, null=True, blank=True)
    type = models.CharField(max_length=50, null=True, blank=True)
    currency_code = models.CharField(max_length=10, null=True, blank=True)
    
    default_account_id = models.IntegerField(null=True, blank=True)
    default_account_code = models.CharField(max_length=64, null=True, blank=True)
    
    odoo_write_date = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'dim_account_journals'
        unique_together = [['tenant', 'odoo_id']]
        indexes = [
            models.Index(fields=['tenant', 'type']),
        ]

    def __str__(self):
        return f"{self.name} [{self.code}]"
