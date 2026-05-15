from django.db import models


class StoredFile(models.Model):
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey('odoo_app.Tenant', on_delete=models.CASCADE, related_name='stored_files', db_column='tenant_id', null=True, blank=True)
    company = models.ForeignKey('odoo_app.Company', on_delete=models.CASCADE, related_name='stored_files', null=True, blank=True)
    file_name = models.TextField()
    stored_filename = models.TextField()
    file_size = models.BigIntegerField()
    content_type = models.TextField(null=True, blank=True)
    storage_path = models.TextField()
    description = models.TextField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stored_files"
        indexes = [
            models.Index(fields=["tenant"], name="idx_stored_files_tenant"),
            models.Index(fields=["tenant", "company"], name="idx_stored_files_comp"),
            models.Index(fields=["tenant", "uploaded_at"], name="idx_stored_files_tenant_ts"),
        ]
