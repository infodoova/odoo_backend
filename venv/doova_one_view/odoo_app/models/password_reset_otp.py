from django.db import models
from django.utils import timezone
import uuid


class PasswordResetOTP(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        'odoo_app.AppUser',
        on_delete=models.CASCADE,
        related_name='password_reset_otps',
        db_column='user_id',
    )
    otp_hash = models.CharField(max_length=255)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'password_reset_otps'

    def is_valid(self) -> bool:
        return not self.used and timezone.now() < self.expires_at
