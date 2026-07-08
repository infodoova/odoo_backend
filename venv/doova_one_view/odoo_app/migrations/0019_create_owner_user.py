from django.db import migrations
from django.contrib.auth.hashers import make_password

def create_owner_user(apps, schema_editor):
    AppUser = apps.get_model('odoo_app', 'AppUser')
    Role = apps.get_model('odoo_app', 'Role')
    UserRole = apps.get_model('odoo_app', 'UserRole')

    # Ensure the owner role exists
    owner_role = Role.objects.filter(name='owner').first()
    if not owner_role:
        return

    # Create the owner user
    owner_email = 'owner@doova.com'
    if not AppUser.objects.filter(email=owner_email).exists():
        user = AppUser.objects.create(
            email=owner_email,
            password_hash=make_password('admin'),
            full_name='System Owner',
            is_active=True,
            is_superuser=False, # Roles manage permissions, but could be true based on the PDF. PDF says "Users with is_superuser=true bypass all permission checks", but we want to test roles. So let's make it False, or leave it False. Wait, if it's the owner role, it doesn't need to be superuser.
        )
        # Assign the role
        UserRole.objects.create(
            user=user,
            role=owner_role
        )

def revert_owner_user(apps, schema_editor):
    AppUser = apps.get_model('odoo_app', 'AppUser')
    AppUser.objects.filter(email='owner@doova.com').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('odoo_app', '0018_seed_roles'),
    ]

    operations = [
        migrations.RunPython(create_owner_user, revert_owner_user),
    ]
