from django.db import models


class Partner(models.Model):
    """Partner dimension (customers & suppliers)"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='partners')
    odoo_id = models.IntegerField()
    name = models.CharField(max_length=500)
    partner_type = models.CharField(max_length=50, null=True, blank=True)
    is_customer = models.BooleanField(default=False)
    is_supplier = models.BooleanField(default=False)
    email = models.EmailField(max_length=255, null=True, blank=True)
    phone = models.CharField(max_length=100, null=True, blank=True)
    country_code = models.CharField(max_length=10, null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    customer_rank = models.IntegerField(default=0)
    supplier_rank = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'dim_partners'
        unique_together = [['tenant', 'odoo_id']]
        indexes = [
            models.Index(fields=['tenant', 'is_customer']),
            models.Index(fields=['tenant', 'is_supplier']),
        ]

    def __str__(self):
        return self.name
