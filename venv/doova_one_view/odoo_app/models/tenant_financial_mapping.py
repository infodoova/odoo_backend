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

    # Configurable Anomaly & Operational Thresholds
    variance_warning_threshold_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=2.00,
        help_text="Variance warning threshold in percent (default 2.0%)"
    )
    variance_critical_threshold_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=10.00,
        help_text="Variance critical threshold in percent (default 10.0%)"
    )
    po_matching_tolerance_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=1.00,
        help_text="PO to Invoice 3-way matching tolerance (default 1.0%)"
    )
    min_completeness_threshold_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=90.00,
        help_text="Minimum data completeness threshold before auto-pause (default 90.0%)"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_financial_mappings'
        
    def __str__(self):
        return f"Financial Mapping for Tenant: {self.tenant.name}"
