# odoo_app/models/account_account_tag.py

from django.db import models


class AccountAccountTag(models.Model):
    """
    Synced from Odoo's account.account.tag model (dim_account_tags).
    Stores financial and tax tags (Operating, Investing, Financing, etc.)
    used for Cash Flow Statement and Tax reporting.
    """
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey(
        'odoo_app.Tenant', on_delete=models.CASCADE, related_name='account_tags'
    )
    company = models.ForeignKey('odoo_app.Company', on_delete=models.SET_NULL, null=True, blank=True)
    odoo_id = models.IntegerField()
    name = models.CharField(max_length=255)
    applicability = models.CharField(max_length=64, null=True, blank=True)
    color = models.IntegerField(null=True, blank=True)
    tax_negate = models.BooleanField(default=False)
    country_name = models.CharField(max_length=255, null=True, blank=True)

    odoo_write_date = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'dim_account_tags'
        unique_together = [['tenant', 'odoo_id']]
        indexes = [
            models.Index(fields=['tenant', 'applicability']),
            models.Index(fields=['tenant', 'name']),
        ]

    def __str__(self):
        return f"{self.name} ({self.applicability})"
