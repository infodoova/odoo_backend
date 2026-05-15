from django.db import models


class Anomaly(models.Model):
    """Detected anomalies"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE)
    company = models.ForeignKey('odoo_app.Company', on_delete=models.SET_NULL, null=True, blank=True)

    anomaly_type = models.CharField(max_length=100)

    SEVERITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]
    severity = models.CharField(max_length=50, choices=SEVERITY_CHOICES, null=True, blank=True)

    detected_date = models.DateField()
    metric_name = models.CharField(max_length=100, null=True, blank=True)
    expected_value = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    actual_value = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    deviation_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    description = models.TextField(null=True, blank=True)
    suggested_action = models.TextField(null=True, blank=True)

    is_resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)

    detected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'anomalies'
        indexes = [
            models.Index(fields=['tenant', 'severity']),
            models.Index(fields=['detected_date']),
        ]
