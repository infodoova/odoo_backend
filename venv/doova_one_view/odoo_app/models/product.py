from django.db import models


class Product(models.Model):
    """Product dimension from product.product"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='products')
    company = models.ForeignKey('odoo_app.Company', on_delete=models.SET_NULL, null=True, blank=True)
    odoo_id = models.IntegerField()
    odoo_template_id = models.IntegerField(null=True, blank=True)
    name = models.CharField(max_length=500)
    default_code = models.CharField(max_length=100, null=True, blank=True)
    barcode = models.CharField(max_length=100, null=True, blank=True)

    PRODUCT_TYPE_CHOICES = [
        ('consu', 'Consumable'),
        ('service', 'Service'),
        ('product', 'Storable Product'),
    ]
    product_type = models.CharField(max_length=50, choices=PRODUCT_TYPE_CHOICES, null=True, blank=True)

    category = models.ForeignKey('odoo_app.ProductCategory', on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    list_price = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    standard_price = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    uom_name = models.CharField(max_length=50, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'dim_products'
        unique_together = [['tenant', 'odoo_id']]
        indexes = [
            models.Index(fields=['tenant', 'is_active']),
            models.Index(fields=['default_code']),
            models.Index(fields=['barcode']),
        ]

    def __str__(self):
        return f"{self.name} ({self.default_code or 'No SKU'})"
