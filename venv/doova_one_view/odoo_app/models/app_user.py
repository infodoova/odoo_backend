from django.db import models
from django.contrib.auth.hashers import check_password as django_check_password, make_password
import uuid


class AppUser(models.Model):
    """Application users (not Odoo users)"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    password_hash = models.CharField(max_length=255)
    full_name = models.CharField(max_length=255, null=True, blank=True)

    is_active = models.BooleanField(default=True)
    is_superuser = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'app_users'

    def __str__(self):
        return self.email
    
    def check_password(self, raw_password: str) -> bool:
        """Check if the provided password matches the stored hash"""
        return django_check_password(raw_password, self.password_hash)
    
    def set_password(self, raw_password: str):
        """Set the password hash for this user"""
        self.password_hash = make_password(raw_password)