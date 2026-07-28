import asyncio
import logging
from typing import Optional
from uuid import UUID

from doova_one_view.api.common.exceptions import NotFoundError, ValidationError

logger = logging.getLogger(__name__)


class PermissionService:

    @staticmethod
    async def get_user_permissions(user_id) -> set[str]:
        """Return the flat set of permission codenames for the given user across all their roles (or all permissions if superuser)."""
        def _fetch():
            from odoo_app.models.app_user import AppUser
            from odoo_app.models.rbac import UserRole, Permission

            user = AppUser.objects.filter(id=user_id).first()
            if user and user.is_superuser:
                return set(Permission.objects.values_list('codename', flat=True))

            user_roles = (
                UserRole.objects
                .filter(user_id=user_id)
                .select_related('role')
                .prefetch_related('role__permissions')
            )
            codenames = set()
            for ur in user_roles:
                for perm in ur.role.permissions.all():
                    codenames.add(perm.codename)
            return codenames

        return await asyncio.to_thread(_fetch)

    @staticmethod
    async def get_user_roles(user_id) -> list[dict]:
        """Return the list of role dicts assigned to the user."""
        def _fetch():
            from odoo_app.models.rbac import UserRole
            return [
                {"id": str(ur.role.id), "name": ur.role.name, "description": ur.role.description}
                for ur in UserRole.objects.filter(user_id=user_id).select_related('role')
            ]

        return await asyncio.to_thread(_fetch)

    @staticmethod
    async def assign_role_to_user(user_id, role_id, assigned_by_id=None) -> dict:
        def _assign():
            from odoo_app.models.app_user import AppUser
            from odoo_app.models.rbac import Role, UserRole

            try:
                user = AppUser.objects.get(id=user_id)
            except AppUser.DoesNotExist:
                raise NotFoundError("User not found")

            try:
                role = Role.objects.get(id=role_id)
            except Role.DoesNotExist:
                raise NotFoundError("Role not found")

            if UserRole.objects.filter(user=user, role=role).exists():
                raise ValidationError("User already has this role")

            UserRole.objects.create(
                user=user,
                role=role,
                assigned_by_id=assigned_by_id
            )
            return {"user_id": str(user_id), "role_id": str(role_id), "role_name": role.name}

        try:
            return await asyncio.to_thread(_assign)
        except (NotFoundError, ValidationError):
            raise
        except Exception as e:
            logger.error(f"Assign role error: {e}")
            raise ValidationError("Failed to assign role")

    @staticmethod
    async def remove_role_from_user(user_id, role_id) -> None:
        def _remove():
            from odoo_app.models.rbac import UserRole
            deleted, _ = UserRole.objects.filter(user_id=user_id, role_id=role_id).delete()
            if not deleted:
                raise NotFoundError("Role assignment not found")

        try:
            await asyncio.to_thread(_remove)
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Remove role error: {e}")
            raise ValidationError("Failed to remove role")

    # ── Role CRUD ──────────────────────────────────────────────────────────────

    @staticmethod
    async def list_roles() -> list[dict]:
        def _fetch():
            from odoo_app.models.rbac import Role
            return [
                {
                    "id": str(r.id),
                    "name": r.name,
                    "description": r.description,
                    "created_at": r.created_at.isoformat(),
                    "permissions": [p.codename for p in r.permissions.all()],
                }
                for r in Role.objects.prefetch_related('permissions').all()
            ]

        return await asyncio.to_thread(_fetch)

    @staticmethod
    async def create_role(name: str, description: str = "") -> dict:
        def _create():
            from odoo_app.models.rbac import Role
            if Role.objects.filter(name=name).exists():
                raise ValidationError("Role with this name already exists")
            role = Role.objects.create(name=name, description=description)
            return {"id": str(role.id), "name": role.name, "description": role.description, "created_at": role.created_at.isoformat(), "permissions": []}

        try:
            return await asyncio.to_thread(_create)
        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"Create role error: {e}")
            raise ValidationError("Failed to create role")

    @staticmethod
    async def assign_permissions_to_role(role_id, permission_codenames: list[str]) -> dict:
        def _assign():
            from odoo_app.models.rbac import Role, Permission, RolePermission

            try:
                role = Role.objects.get(id=role_id)
            except Role.DoesNotExist:
                raise NotFoundError("Role not found")

            perms = Permission.objects.filter(codename__in=permission_codenames)
            found = set(p.codename for p in perms)
            missing = set(permission_codenames) - found
            if missing:
                raise NotFoundError(f"Permissions not found: {', '.join(missing)}")

            for perm in perms:
                RolePermission.objects.get_or_create(role=role, permission=perm)

            return {
                "id": str(role.id),
                "name": role.name,
                "description": role.description,
                "created_at": role.created_at.isoformat(),
                "permissions": [p.codename for p in role.permissions.all()],
            }

        try:
            return await asyncio.to_thread(_assign)
        except (NotFoundError, ValidationError):
            raise
        except Exception as e:
            logger.error(f"Assign permissions error: {e}")
            raise ValidationError("Failed to assign permissions")

    @staticmethod
    async def remove_permission_from_role(role_id, permission_id) -> None:
        def _remove():
            from odoo_app.models.rbac import RolePermission
            deleted, _ = RolePermission.objects.filter(role_id=role_id, permission_id=permission_id).delete()
            if not deleted:
                raise NotFoundError("Permission assignment not found")

        try:
            await asyncio.to_thread(_remove)
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Remove permission error: {e}")
            raise ValidationError("Failed to remove permission")

    # ── User listing ──────────────────────────────────────────────────────────

    @staticmethod
    async def list_users_with_roles() -> list[dict]:
        def _fetch():
            from odoo_app.models.app_user import AppUser
            users = (
                AppUser.objects
                .prefetch_related('user_roles__role')
                .all()
                .order_by('-created_at')
            )
            result = []
            for user in users:
                roles = [ur.role.name for ur in user.user_roles.all()]
                result.append({
                    "id": str(user.id),
                    "email": user.email,
                    "full_name": user.full_name,
                    "is_active": user.is_active,
                    "created_at": user.created_at.isoformat(),
                    "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
                    "roles": roles,
                })
            return result

        return await asyncio.to_thread(_fetch)

    # ── Permission CRUD ────────────────────────────────────────────────────────

    @staticmethod
    async def list_permissions() -> list[dict]:
        def _fetch():
            from odoo_app.models.rbac import Permission
            return [
                {"id": str(p.id), "codename": p.codename, "description": p.description, "created_at": p.created_at.isoformat()}
                for p in Permission.objects.all()
            ]

        return await asyncio.to_thread(_fetch)

    @staticmethod
    async def create_permission(codename: str, description: str = "") -> dict:
        def _create():
            from odoo_app.models.rbac import Permission
            if Permission.objects.filter(codename=codename).exists():
                raise ValidationError("Permission with this codename already exists")
            perm = Permission.objects.create(codename=codename, description=description)
            return {"id": str(perm.id), "codename": perm.codename, "description": perm.description, "created_at": perm.created_at.isoformat()}

        try:
            return await asyncio.to_thread(_create)
        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"Create permission error: {e}")
            raise ValidationError("Failed to create permission")
