from django.db import models

class TenantFinancialMapping(models.Model):
    """
    Configuration mapping for tenant-specific accounting configurations.
    Allows dynamic bucketing of account codes into Net Working Capital categories.
    """
    tenant = models.OneToOneField('odoo_app.Tenant', on_delete=models.CASCADE, related_name='financial_mapping')
    accrued_expense_prefixes = models.JSONField(
        default=list, 
        blank=True,
        help_text='List of account code prefixes (e.g. ["21", "210"]) for accrued expenses.'
    )
    short_term_debt_prefixes = models.JSONField(
        default=list, 
        blank=True,
        help_text='List of account code prefixes (e.g. ["22", "220"]) for short-term debt.'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_financial_mappings'
        
    def __str__(self):
        return f"Financial Mapping for Tenant: {self.tenant.name}"
