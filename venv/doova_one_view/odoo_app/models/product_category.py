from django.db import models


class ProductCategory(models.Model):
    """Product category hierarchy"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='product_categories')
    odoo_id = models.IntegerField()
    name = models.CharField(max_length=255)
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children')
    complete_name = models.CharField(max_length=500, null=True, blank=True)

    class Meta:
        db_table = 'dim_product_categories'
        unique_together = [['tenant', 'odoo_id']]
        verbose_name_plural = 'Product Categories'

    def __str__(self):
        return self.complete_name or self.name
