from django.db import models


class DailyKPI(models.Model):
    """Pre-aggregated daily KPIs"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE)
    company = models.ForeignKey('odoo_app.Company', on_delete=models.SET_NULL, null=True, blank=True)
    date_dimension = models.ForeignKey('odoo_app.TimeDimension', on_delete=models.SET_NULL, null=True, blank=True, db_column='date_id')

    sales_count = models.IntegerField(default=0)
    sales_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    sales_margin = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    invoices_count = models.IntegerField(default=0)
    invoices_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    outstanding_receivables = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    bills_count = models.IntegerField(default=0)
    bills_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    outstanding_payables = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    stock_moves_in = models.IntegerField(default=0)
    stock_moves_out = models.IntegerField(default=0)

    purchase_orders_count = models.IntegerField(default=0)
    purchase_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'analytics_kpis_daily'
        unique_together = [['tenant', 'company', 'date_dimension']]

    @property
    def profit(self):
        return self.sales_amount - self.bills_amount
