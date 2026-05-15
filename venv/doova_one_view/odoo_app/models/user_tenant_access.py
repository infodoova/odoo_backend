from django.db import models
from django.contrib.postgres.fields import ArrayField


class UserTenantAccess(models.Model):
    """User access control per tenant"""
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey('odoo_app.AppUser', on_delete=models.CASCADE, related_name='tenant_access')
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='user_access')
    can_view_all_companies = models.BooleanField(default=False)
    allowed_company_ids = ArrayField(models.IntegerField(), null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'user_tenant_access'
        unique_together = [['user', 'tenant']]
