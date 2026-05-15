from django.db import models


class Forecast(models.Model):
    """Predictive forecasts"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE)
    company = models.ForeignKey('odoo_app.Company', on_delete=models.SET_NULL, null=True, blank=True)

    FORECAST_TYPE_CHOICES = [
        ('sales', 'Sales Forecast'),
        ('inventory_depletion', 'Inventory Depletion'),
        ('cashflow', 'Cash Flow Projection'),
    ]
    forecast_type = models.CharField(max_length=50, choices=FORECAST_TYPE_CHOICES)

    MODEL_CHOICES = [
        ('prophet', 'Prophet'),
        ('arima', 'ARIMA'),
        ('xgboost', 'XGBoost'),
    ]
    model_used = models.CharField(max_length=50, choices=MODEL_CHOICES, null=True, blank=True)

    product = models.ForeignKey('odoo_app.Product', on_delete=models.SET_NULL, null=True, blank=True)

    forecast_date = models.DateField()
    predicted_value = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    confidence_lower = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    confidence_upper = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    model_accuracy = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)

    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'forecasts'
        unique_together = [['tenant', 'company', 'forecast_type', 'product', 'forecast_date']]
