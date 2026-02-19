from django.db import models


class Company(models.Model):
    """Company dimension from res.company"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='companies')
    odoo_id = models.IntegerField()
    name = models.CharField(max_length=255)
    currency_code = models.CharField(max_length=10, null=True, blank=True)
    country_code = models.CharField(max_length=10, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'dim_companies'
        unique_together = [['tenant', 'odoo_id']]
        verbose_name_plural = 'Companies'

    def __str__(self):
        return f"{self.name} ({self.tenant.name})"
