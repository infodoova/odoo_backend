from django.db import models


class StoredFile(models.Model):
    id = models.BigAutoField(primary_key=True)
    tenant_id = models.TextField()
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
            models.Index(fields=["tenant_id"], name="idx_stored_files_tenant"),
            models.Index(fields=["tenant_id", "uploaded_at"], name="idx_stored_files_tenant_ts"),
        ]
