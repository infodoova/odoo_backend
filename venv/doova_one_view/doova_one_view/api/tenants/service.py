"""
Tenant service - Business logic layer
"""

import asyncio
from typing import List, Optional, Dict, Tuple
from datetime import datetime
import logging
from django.utils import timezone

from odoo_app.models.tenant import Tenant
from odoo_app.models.user_tenant_access import UserTenantAccess
from django.conf import settings

from doova_one_view.api.common.exceptions import NotFoundError, PermissionError, ValidationError
from doova_one_view.api.common.utils import encrypt_api_key, decrypt_api_key
from doova_one_view.api.tenants.schemas import TenantCreate, TenantUpdate, TenantRead, SyncResponse, SyncStatusResponse

logger = logging.getLogger(__name__)


class TenantService:
    """Service for tenant operations"""
    
    @staticmethod
    def _check_access(user_id: Optional[str], tenant: Tenant) -> None:
        """Check if user has access to tenant (superusers always have access)"""
        if not user_id:
            return
        from odoo_app.models.app_user import AppUser
        try:
            user_obj = AppUser.objects.get(id=user_id)
            if user_obj.is_superuser:
                return
            if not UserTenantAccess.objects.filter(user_id=user_id, tenant=tenant).exists():
                raise PermissionError("User does not have access to this tenant")
        except AppUser.DoesNotExist:
            raise PermissionError("User does not exist")

    @staticmethod
    async def create_tenant(data: TenantCreate, user_id: str) -> TenantRead:
        """
        Create a new tenant
        
        Args:
            data: Tenant creation data
            user_id: ID of user creating the tenant
            
        Returns:
            TenantRead: Created tenant data
            
        Raises:
            ValidationError: If validation fails
        """
        def _create():
            # Encrypt API key
            api_key_encrypted = encrypt_api_key(data.odoo_api_key) if data.odoo_api_key else b''
            
            # Create tenant
            tenant = Tenant.objects.create(
                name=data.name,
                odoo_url=str(data.odoo_url).rstrip('/'),
                odoo_database=data.odoo_database,
                odoo_username=getattr(data, 'odoo_username', '') or '',
                api_key_encrypted=api_key_encrypted,
                is_active=data.is_active,
                sync_status='pending'
            )
            
            # Grant user access to tenant
            UserTenantAccess.objects.create(
                user_id=user_id,
                tenant=tenant,
                can_view_all_companies=True
            )
            
            logger.info(f"Tenant created: {tenant.name} (ID: {tenant.id})")
            return tenant
        
        try:
            tenant = await asyncio.to_thread(_create)
            user_count = await TenantService.get_tenant_user_count(str(tenant.id))
            
            return TenantRead(
                id=str(tenant.id),
                name=tenant.name,
                odoo_url=tenant.odoo_url,
                odoo_database=tenant.odoo_database,
                odoo_username=tenant.odoo_username or '',
                is_active=tenant.is_active,
                sync_status=tenant.sync_status,
                last_sync_at=tenant.last_sync_at,
                created_at=tenant.created_at,
                updated_at=tenant.updated_at,
                user_count=user_count
            )
        except Exception as e:
            logger.error(f"Error creating tenant: {str(e)}")
            raise ValidationError(f"Failed to create tenant: {str(e)}")
    
    @staticmethod
    async def get_tenant(tenant_id: str, user_id: Optional[str] = None) -> TenantRead:
        """
        Get tenant by ID
        
        Args:
            tenant_id: Tenant UUID
            user_id: Optional user ID for access check
            
        Returns:
            TenantRead: Tenant data
            
        Raises:
            NotFoundError: If tenant not found
            PermissionError: If user doesn't have access
        """
        def _get():
            try:
                tenant = Tenant.objects.get(id=tenant_id)
            except Tenant.DoesNotExist:
                raise NotFoundError("Tenant", tenant_id)
            
            # Check user access if user_id provided
            TenantService._check_access(user_id, tenant)
            
            return tenant
        
        tenant = await asyncio.to_thread(_get)
        user_count = await TenantService.get_tenant_user_count(str(tenant.id))
        
        return TenantRead(
            id=str(tenant.id),
            name=tenant.name,
            odoo_url=tenant.odoo_url,
            odoo_database=tenant.odoo_database,
            odoo_username=tenant.odoo_username or '',
            is_active=tenant.is_active,
            sync_status=tenant.sync_status,
            last_sync_at=tenant.last_sync_at,
            created_at=tenant.created_at,
            updated_at=tenant.updated_at,
            user_count=user_count
        )
    
    @staticmethod
    async def list_tenants(
        user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[TenantRead]:
        """
        List tenants
        
        Args:
            user_id: Optional user ID to filter by access
            limit: Maximum number of results
            offset: Number of results to skip
            
        Returns:
            List[TenantRead]: List of tenant data
        """
        def _list():
            from django.db.models import Count
            from odoo_app.models.app_user import AppUser
            if user_id:
                try:
                    user_obj = AppUser.objects.get(id=user_id)
                    if user_obj.is_superuser:
                        qs = Tenant.objects.all().order_by('-created_at')
                    else:
                        access_records = UserTenantAccess.objects.filter(
                            user_id=user_id
                        ).values_list('tenant_id', flat=True)
                        qs = Tenant.objects.filter(id__in=access_records).order_by('-created_at')
                except AppUser.DoesNotExist:
                    qs = Tenant.objects.none()
            else:
                qs = Tenant.objects.all().order_by('-created_at')
            
            tenants = list(qs[offset:offset+limit])
            
            tenant_ids = [t.id for t in tenants]
            counts = UserTenantAccess.objects.filter(tenant_id__in=tenant_ids).values('tenant_id').annotate(c=Count('id'))
            count_map = {str(row['tenant_id']): row['c'] for row in counts}
            
            result = []
            for t in tenants:
                user_count = count_map.get(str(t.id), 0)
                result.append(TenantRead(
                    id=str(t.id),
                    name=t.name,
                    odoo_url=t.odoo_url,
                    odoo_database=t.odoo_database,
                    odoo_username=t.odoo_username or '',
                    is_active=t.is_active,
                    sync_status=t.sync_status,
                    last_sync_at=t.last_sync_at,
                    created_at=t.created_at,
                    updated_at=t.updated_at,
                    user_count=user_count
                ))
            return result
        
        return await asyncio.to_thread(_list)
    
    # ── Tenant access management ───────────────────────────────────────────────

    @staticmethod
    async def list_all_tenants_simple() -> list:
        """List all tenants (id + name only) — for admin dropdowns."""
        def _fetch():
            return list(
                Tenant.objects.all().order_by('name').values('id', 'name', 'is_active')
            )
        rows = await asyncio.to_thread(_fetch)
        return [{"id": str(r["id"]), "name": r["name"], "is_active": r["is_active"]} for r in rows]

    @staticmethod
    async def get_user_tenant_accesses(user_id: str) -> list:
        """Return all tenant accesses for a user."""
        def _fetch():
            from odoo_app.models.user_tenant_access import UserTenantAccess
            records = (
                UserTenantAccess.objects
                .filter(user_id=user_id)
                .select_related('tenant')
                .order_by('tenant__name')
            )
            return [
                {
                    "tenant_id": str(r.tenant.id),
                    "tenant_name": r.tenant.name,
                    "tenant_is_active": r.tenant.is_active,
                    "can_view_all_companies": r.can_view_all_companies,
                    "granted_at": r.created_at.isoformat(),
                }
                for r in records
            ]
        return await asyncio.to_thread(_fetch)

    @staticmethod
    async def grant_tenant_access(user_id: str, tenant_id: str) -> dict:
        """Grant a user access to a tenant."""
        def _grant():
            from odoo_app.models.app_user import AppUser
            from odoo_app.models.user_tenant_access import UserTenantAccess

            try:
                user = AppUser.objects.get(id=user_id)
            except AppUser.DoesNotExist:
                raise NotFoundError("User", user_id)

            try:
                tenant = Tenant.objects.get(id=tenant_id)
            except Tenant.DoesNotExist:
                raise NotFoundError("Tenant", tenant_id)

            if UserTenantAccess.objects.filter(user=user, tenant=tenant).exists():
                raise ValidationError("User already has access to this tenant")

            access = UserTenantAccess.objects.create(
                user=user,
                tenant=tenant,
                can_view_all_companies=True,
            )
            return {
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
                "tenant_is_active": tenant.is_active,
                "can_view_all_companies": access.can_view_all_companies,
                "granted_at": access.created_at.isoformat(),
            }

        try:
            return await asyncio.to_thread(_grant)
        except (NotFoundError, ValidationError):
            raise
        except Exception as e:
            logger.error(f"Grant tenant access error: {e}")
            raise ValidationError("Failed to grant tenant access")

    @staticmethod
    async def revoke_tenant_access(user_id: str, tenant_id: str) -> None:
        """Revoke a user's access to a tenant."""
        def _revoke():
            from odoo_app.models.user_tenant_access import UserTenantAccess
            deleted, _ = UserTenantAccess.objects.filter(
                user_id=user_id, tenant_id=tenant_id
            ).delete()
            if not deleted:
                raise NotFoundError("Tenant access", f"{user_id}/{tenant_id}")

        try:
            await asyncio.to_thread(_revoke)
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Revoke tenant access error: {e}")
            raise ValidationError("Failed to revoke tenant access")

    # ── End tenant access management ───────────────────────────────────────────

    @staticmethod
    async def update_tenant(
        tenant_id: str,
        data: TenantUpdate,
        user_id: Optional[str] = None
    ) -> TenantRead:
        """
        Update tenant
        
        Args:
            tenant_id: Tenant UUID
            data: Update data
            user_id: Optional user ID for access check
            
        Returns:
            TenantRead: Updated tenant data
            
        Raises:
            NotFoundError: If tenant not found
            PermissionError: If user doesn't have access
        """
        def _update():
            try:
                tenant = Tenant.objects.get(id=tenant_id)
            except Tenant.DoesNotExist:
                raise NotFoundError("Tenant", tenant_id)
            
            # Check user access if user_id provided
            TenantService._check_access(user_id, tenant)
            
            # Update fields
            update_data = data.model_dump(exclude_unset=True)
            if 'name' in update_data:
                tenant.name = update_data['name']
            if 'odoo_url' in update_data:
                tenant.odoo_url = str(update_data['odoo_url']).rstrip('/')
            if 'odoo_database' in update_data:
                tenant.odoo_database = update_data['odoo_database']
            if 'odoo_api_key' in update_data:
                tenant.api_key_encrypted = encrypt_api_key(update_data['odoo_api_key'])
            if 'odoo_username' in update_data:
                tenant.odoo_username = update_data['odoo_username'] or ''
            if 'is_active' in update_data:
                tenant.is_active = update_data['is_active']
            
            tenant.save()
            logger.info(f"Tenant updated: {tenant.name} (ID: {tenant.id})")
            return tenant
        
        tenant = await asyncio.to_thread(_update)
        user_count = await TenantService.get_tenant_user_count(str(tenant.id))
        
        return TenantRead(
            id=str(tenant.id),
            name=tenant.name,
            odoo_url=tenant.odoo_url,
            odoo_database=tenant.odoo_database,
            odoo_username=tenant.odoo_username or '',
            is_active=tenant.is_active,
            sync_status=tenant.sync_status,
            last_sync_at=tenant.last_sync_at,
            created_at=tenant.created_at,
            updated_at=tenant.updated_at,
            user_count=user_count
        )
    
    @staticmethod
    async def delete_tenant(tenant_id: str, user_id: Optional[str] = None) -> bool:
        """
        Delete tenant
        
        Args:
            tenant_id: Tenant UUID
            user_id: Optional user ID for access check
            
        Returns:
            bool: True if deleted
            
        Raises:
            NotFoundError: If tenant not found
            PermissionError: If user doesn't have access
        """
        def _delete():
            try:
                tenant = Tenant.objects.get(id=tenant_id)
            except Tenant.DoesNotExist:
                raise NotFoundError("Tenant", tenant_id)
            
            # Check user access if user_id provided
            TenantService._check_access(user_id, tenant)
            
            logger.info(f"Tenant deleted: {tenant.name} (ID: {tenant.id})")
            tenant.delete()
            return True
        
        return await asyncio.to_thread(_delete)

    @staticmethod
    async def deactivate_tenant(tenant_id: str, user_id: Optional[str] = None) -> TenantRead:
        """
        Deactivate a tenant
        
        Args:
            tenant_id: Tenant UUID
            user_id: Optional user ID for access check
            
        Returns:
            TenantRead: Updated tenant data with is_active=False
            
        Raises:
            NotFoundError: If tenant not found
            PermissionError: If user doesn't have access
        """
        def _deactivate():
            try:
                tenant = Tenant.objects.get(id=tenant_id)
            except Tenant.DoesNotExist:
                raise NotFoundError("Tenant", tenant_id)
            
            TenantService._check_access(user_id, tenant)
            
            tenant.is_active = False
            tenant.save(update_fields=['is_active', 'updated_at'])
            logger.info(f"Tenant deactivated: {tenant.name} (ID: {tenant.id})")
            return tenant
        
        tenant = await asyncio.to_thread(_deactivate)
        user_count = await TenantService.get_tenant_user_count(str(tenant.id))
        
        return TenantRead(
            id=str(tenant.id),
            name=tenant.name,
            odoo_url=tenant.odoo_url,
            odoo_database=tenant.odoo_database,
            odoo_username=tenant.odoo_username or '',
            is_active=tenant.is_active,
            sync_status=tenant.sync_status,
            last_sync_at=tenant.last_sync_at,
            created_at=tenant.created_at,
            updated_at=tenant.updated_at,
            user_count=user_count
        )

    @staticmethod
    async def activate_tenant(tenant_id: str, user_id: Optional[str] = None) -> TenantRead:
        """
        Activate a tenant
        
        Args:
            tenant_id: Tenant UUID
            user_id: Optional user ID for access check
            
        Returns:
            TenantRead: Updated tenant data with is_active=True
            
        Raises:
            NotFoundError: If tenant not found
            PermissionError: If user doesn't have access
        """
        def _activate():
            try:
                tenant = Tenant.objects.get(id=tenant_id)
            except Tenant.DoesNotExist:
                raise NotFoundError("Tenant", tenant_id)
            
            TenantService._check_access(user_id, tenant)
            
            tenant.is_active = True
            tenant.save(update_fields=['is_active', 'updated_at'])
            logger.info(f"Tenant activated: {tenant.name} (ID: {tenant.id})")
            return tenant
        
        tenant = await asyncio.to_thread(_activate)
        user_count = await TenantService.get_tenant_user_count(str(tenant.id))
        
        return TenantRead(
            id=str(tenant.id),
            name=tenant.name,
            odoo_url=tenant.odoo_url,
            odoo_database=tenant.odoo_database,
            odoo_username=tenant.odoo_username or '',
            is_active=tenant.is_active,
            sync_status=tenant.sync_status,
            last_sync_at=tenant.last_sync_at,
            created_at=tenant.created_at,
            updated_at=tenant.updated_at,
            user_count=user_count
        )

    
    @staticmethod
    async def get_tenant_user_count(tenant_id: str) -> int:
        """
        Get number of users with access to tenant
        
        Args:
            tenant_id: Tenant UUID
            
        Returns:
            int: Number of users
        """
        def _count():
            return UserTenantAccess.objects.filter(tenant_id=tenant_id).count()
        
        return await asyncio.to_thread(_count)
    
    @staticmethod
    async def run_full_sync(tenant_id: str) -> SyncResponse:
        """
        Run full Odoo sync for tenant
        
        Args:
            tenant_id: Tenant UUID
            
        Returns:
            SyncResponse: Sync results
            
        Raises:
            NotFoundError: If tenant not found
        """
        def _run_sync():
            from odoo_app.etl import TenantConfig, ETLOrchestrator
            
            try:
                tenant = Tenant.objects.get(id=tenant_id)
            except Tenant.DoesNotExist:
                raise NotFoundError("Tenant", tenant_id)
            
            # Decrypt API key
            api_key = decrypt_api_key(tenant.api_key_encrypted) if tenant.api_key_encrypted else ""
            
            # Create tenant config
            tenant_config = TenantConfig(
                tenant_id=str(tenant.id),
                name=tenant.name,
                odoo_url=tenant.odoo_url,
                odoo_database=tenant.odoo_database,
                odoo_username=tenant.odoo_username or getattr(settings, 'ODOO_USERNAME', ''),
                odoo_api_key=api_key
            )
            
            # Build DB connection string
            db_config = settings.DATABASES['default']
            db_conn_string = (
                f"host={db_config.get('HOST', 'localhost')} "
                f"port={db_config.get('PORT', 5432)} "
                f"dbname={db_config.get('NAME')} "
                f"user={db_config.get('USER')} "
                f"password={db_config.get('PASSWORD')}"
            )
            
            try:
                # Run sync
                orchestrator = ETLOrchestrator(tenant_config, db_conn_string)
                results = orchestrator.run_full_sync()
                
                # Check results - if ignored, just return them
                if results.get('status') == 'ignored':
                    return {
                        'message': 'Sync ignored - already running',
                        'tenant_id': str(tenant.id),
                        'sync_type': 'full',
                        'results': results,
                        'status': 'success',
                        'message_type': 'info'
                    }

                # Update sync status (The orchestrator already sets it to active, but we ensure Django model consistency)
                tenant.refresh_from_db()
                
                # Format results
                formatted_results = {}
                for key, value in results.get('phases', {}).items():
                    formatted_results[key] = value
                
                return {
                    'message': 'Sync completed successfully',
                    'tenant_id': str(tenant.id),
                    'sync_type': 'full',
                    'results': formatted_results,
                    'status': 'success',
                    'message_type': 'success'
                }
            except Exception as e:
                tenant.sync_status = 'error'
                tenant.save()
                raise e
        
        result = await asyncio.to_thread(_run_sync)
        return SyncResponse(**result)
    
    @staticmethod
    async def run_delta_sync(tenant_id: str) -> SyncResponse:
        """
        Run incremental delta sync for tenant
        
        Args:
            tenant_id: Tenant UUID
            
        Returns:
            SyncResponse: Sync results
            
        Raises:
            NotFoundError: If tenant not found
        """
        def _run_delta_sync():
            from odoo_app.etl import TenantConfig, ETLOrchestrator
            
            try:
                tenant = Tenant.objects.get(id=tenant_id)
            except Tenant.DoesNotExist:
                raise NotFoundError("Tenant", tenant_id)
            
            # Decrypt API key
            api_key = decrypt_api_key(tenant.api_key_encrypted) if tenant.api_key_encrypted else ""
            
            # Create tenant config
            tenant_config = TenantConfig(
                tenant_id=str(tenant.id),
                name=tenant.name,
                odoo_url=tenant.odoo_url,
                odoo_database=tenant.odoo_database,
                odoo_username=tenant.odoo_username or getattr(settings, 'ODOO_USERNAME', ''),
                odoo_api_key=api_key
            )
            
            # Build DB connection string
            db_config = settings.DATABASES['default']
            db_conn_string = (
                f"host={db_config.get('HOST', 'localhost')} "
                f"port={db_config.get('PORT', 5432)} "
                f"dbname={db_config.get('NAME')} "
                f"user={db_config.get('USER')} "
                f"password={db_config.get('PASSWORD')}"
            )
            
            try:
                # Run delta sync
                orchestrator = ETLOrchestrator(tenant_config, db_conn_string)
                results = orchestrator.run_delta_sync()
                
                if results.get('status') == 'ignored':
                     return {
                        'message': 'Delta sync ignored - already running',
                        'tenant_id': str(tenant.id),
                        'sync_type': 'delta',
                        'results': results,
                        'status': 'success',
                        'message_type': 'info'
                    }

                # Refresh and update
                tenant.refresh_from_db()
                
                # Format results
                formatted_results = {}
                for key, value in results.get('phases', {}).items():
                    formatted_results[key] = value
                
                return {
                    'message': 'Delta sync completed successfully',
                    'tenant_id': str(tenant.id),
                    'sync_type': 'delta',
                    'results': formatted_results,
                    'status': 'success',
                    'message_type': 'success'
                }
            except Exception as e:
                tenant.sync_status = 'error'
                tenant.save()
                raise e
        
        result = await asyncio.to_thread(_run_delta_sync)
        return SyncResponse(**result)

    @staticmethod
    async def run_smart_sync(tenant_id: str) -> SyncResponse:
        """
        Run intelligent sync for tenant.
        Automatically decides between full and incremental based on history.
        """
        def _run_smart():
            from odoo_app.etl import TenantConfig, ETLOrchestrator
            
            try:
                tenant = Tenant.objects.get(id=tenant_id)
            except Tenant.DoesNotExist:
                raise NotFoundError("Tenant", tenant_id)
            
            # Decrypt API key
            api_key = decrypt_api_key(tenant.api_key_encrypted) if tenant.api_key_encrypted else ""
            
            # Create tenant config
            tenant_config = TenantConfig(
                tenant_id=str(tenant.id),
                name=tenant.name,
                odoo_url=tenant.odoo_url,
                odoo_database=tenant.odoo_database,
                odoo_username=tenant.odoo_username or getattr(settings, 'ODOO_USERNAME', ''),
                odoo_api_key=api_key
            )
            
            # Build DB connection string
            db_config = settings.DATABASES['default']
            db_conn_string = (
                f"host={db_config.get('HOST', 'localhost')} "
                f"port={db_config.get('PORT', 5432)} "
                f"dbname={db_config.get('NAME')} "
                f"user={db_config.get('USER')} "
                f"password={db_config.get('PASSWORD')}"
            )
            
            try:
                # Run smart sync
                orchestrator = ETLOrchestrator(tenant_config, db_conn_string)
                results = orchestrator.run_smart_sync()
                
                if results.get('status') == 'ignored':
                     return {
                        'message': 'Smart sync ignored - already running',
                        'tenant_id': str(tenant.id),
                        'sync_type': 'smart',
                        'results': results,
                        'status': 'success',
                        'message_type': 'info'
                    }

                # Refresh and update
                tenant.refresh_from_db()
                
                # Format results
                formatted_results = {}
                for key, value in results.get('phases', {}).items():
                    formatted_results[key] = value
                
                return {
                    'message': 'Smart sync completed successfully',
                    'tenant_id': str(tenant.id),
                    'sync_type': 'smart',
                    'results': formatted_results,
                    'status': 'success',
                    'message_type': 'success'
                }
            except Exception as e:
                tenant.sync_status = 'error'
                tenant.save()
                raise e
        
        result = await asyncio.to_thread(_run_smart)
        return SyncResponse(**result)
    
    @staticmethod
    async def get_sync_status(tenant_id: str) -> SyncStatusResponse:
        """
        Get sync status for tenant
        
        Args:
            tenant_id: Tenant UUID
            
        Returns:
            SyncStatusResponse: Sync status data
            
        Raises:
            NotFoundError: If tenant not found
        """
        def _get_status():
            from odoo_app.etl import TenantConfig, ETLOrchestrator
            
            try:
                tenant = Tenant.objects.get(id=tenant_id)
            except Tenant.DoesNotExist:
                raise NotFoundError("Tenant", tenant_id)
            
            # Decrypt API key
            api_key = decrypt_api_key(tenant.api_key_encrypted) if tenant.api_key_encrypted else ""
            
            # Create tenant config
            tenant_config = TenantConfig(
                tenant_id=str(tenant.id),
                name=tenant.name,
                odoo_url=tenant.odoo_url,
                odoo_database=tenant.odoo_database,
                odoo_username=getattr(settings, 'ODOO_USERNAME', ''),
                odoo_api_key=api_key
            )
            
            # Build DB connection string
            db_config = settings.DATABASES['default']
            db_conn_string = (
                f"host={db_config.get('HOST', 'localhost')} "
                f"port={db_config.get('PORT', 5432)} "
                f"dbname={db_config.get('NAME')} "
                f"user={db_config.get('USER')} "
                f"password={db_config.get('PASSWORD')}"
            )
            
            # Get status
            orchestrator = ETLOrchestrator(tenant_config, db_conn_string)
            sync_status = orchestrator.get_sync_status()
            
            return {
                'tenant_id': str(tenant.id),
                'sync_status': tenant.sync_status,
                'last_sync_at': tenant.last_sync_at,
                'last_sync_results': sync_status
            }
        
        result = await asyncio.to_thread(_get_status)
        return SyncStatusResponse(**result)
