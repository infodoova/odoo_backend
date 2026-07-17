from django.db import models


class AccountPartialReconcile(models.Model):
    """Reconciliation links between account move lines (e.g. payment to invoice)"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='partial_reconciles')
    
    odoo_id = models.IntegerField()
    
    debit_move_line = models.ForeignKey(
        'odoo_app.AccountMoveLine', 
        on_delete=models.CASCADE, 
        related_name='reconciled_debits',
        null=True, 
        blank=True
    )
    credit_move_line = models.ForeignKey(
        'odoo_app.AccountMoveLine', 
        on_delete=models.CASCADE, 
        related_name='reconciled_credits',
        null=True, 
        blank=True
    )
    
    amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    max_date = models.DateField(null=True, blank=True)
    
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'fact_account_partial_reconciles'
        unique_together = [['tenant', 'odoo_id']]
        indexes = [
            models.Index(fields=['tenant', 'debit_move_line']),
            models.Index(fields=['tenant', 'credit_move_line']),
        ]
