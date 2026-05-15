from django.db import models


class User(models.Model):
    """User dimension (salespeople) from res.users"""
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='odoo_users')
    odoo_id = models.IntegerField()
    name = models.CharField(max_length=255)
    email = models.EmailField(max_length=255, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'dim_users'
        unique_together = [['tenant', 'odoo_id']]

    def __str__(self):
        return self.name
