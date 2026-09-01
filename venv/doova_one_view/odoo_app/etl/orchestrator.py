"""
ETL Orchestrator
Main coordinator for all sync operations
"""

import logging
import time
from typing import Dict, List, Any
from odoo_app.etl.config import TenantConfig
from odoo_app.etl.clients.odoo_client import OdooClient
from odoo_app.etl.managers.database_manager import DatabaseManager
from odoo_app.etl.syncs.company_synchronizer import CompanySynchronizer
from odoo_app.etl.syncs.currency_synchronizer import CurrencySynchronizer
from odoo_app.etl.syncs.product_synchronizer import ProductCategorySynchronizer, ProductSynchronizer
from odoo_app.etl.syncs.partner_synchronizer import PartnerSynchronizer
from odoo_app.etl.syncs.user_synchronizer import UserSynchronizer
from odoo_app.etl.syncs.time_synchronizer import TimeDimensionSynchronizer
from odoo_app.etl.syncs.sales_synchronizer import SalesOrderSynchronizer
from odoo_app.etl.syncs.stock_lot_synchronizer import LotSynchronizer
from odoo_app.etl.syncs.stock_picking_synchronizer import StockPickingSynchronizer
from odoo_app.etl.syncs.stock_move_synchronizer import StockMoveSynchronizer
from odoo_app.etl.syncs.stock_quant_synchronizer import StockQuantSynchronizer
from odoo_app.etl.syncs.accounting_synchronizer import AccountMoveSynchronizer
from odoo_app.etl.syncs.purchase_synchronizer import PurchaseOrderSynchronizer
from odoo_app.etl.syncs.chart_of_accounts_synchronizer import ChartOfAccountsSynchronizer
from odoo_app.etl.syncs.account_tag_synchronizer import AccountTagSynchronizer
from odoo_app.etl.syncs.currency_rate_synchronizer import CurrencyRateSynchronizer
from odoo_app.etl.syncs.bank_statement_synchronizer import BankStatementSynchronizer
from odoo_app.etl.syncs.account_partial_reconcile_synchronizer import AccountPartialReconcileSynchronizer

logger = logging.getLogger(__name__)


class ETLOrchestrator:
    """
    Main ETL coordinator
    Manages the overall sync workflow for a tenant
    """
    
    def __init__(self, tenant_config: TenantConfig, db_connection_string: str):
        """
        Initialize ETL orchestrator
        
        Args:
            tenant_config: Configuration for Odoo tenant
            db_connection_string: PostgreSQL connection string
        """
        self.tenant_config = tenant_config
        self.odoo = OdooClient(tenant_config)
        self.db = DatabaseManager(db_connection_string)
        
        # Initialize all synchronizers
        self.company_sync = CompanySynchronizer(self.odoo, self.db)
        self.category_sync = ProductCategorySynchronizer(self.odoo, self.db)
        self.product_sync = ProductSynchronizer(self.odoo, self.db)
        self.partner_sync = PartnerSynchronizer(self.odoo, self.db)
        self.user_sync = UserSynchronizer(self.odoo, self.db)
        self.time_sync = TimeDimensionSynchronizer(self.odoo, self.db)
        self.lot_sync = LotSynchronizer(self.odoo, self.db)
        self.picking_sync = StockPickingSynchronizer(self.odoo, self.db)
        self.move_sync = StockMoveSynchronizer(self.odoo, self.db)
        self.quant_sync = StockQuantSynchronizer(self.odoo, self.db)
        self.currency_sync = CurrencySynchronizer(self.odoo, self.db)
        self.sales_order_sync = SalesOrderSynchronizer(self.odoo, self.db)
        self.purchase_order_sync = PurchaseOrderSynchronizer(self.odoo, self.db)
        self.account_move_sync = AccountMoveSynchronizer(self.odoo, self.db)
        self.account_tag_sync = AccountTagSynchronizer(self.odoo, self.db)
        self.chart_of_accounts_sync = ChartOfAccountsSynchronizer(self.odoo, self.db)
        self.currency_rate_sync = CurrencyRateSynchronizer(self.odoo, self.db)
        from odoo_app.etl.syncs.journal_synchronizer import JournalSynchronizer
        self.journal_sync = JournalSynchronizer(self.odoo, self.db)
        self.bank_statement_sync = BankStatementSynchronizer(self.odoo, self.db)
        self.account_partial_reconcile_sync = AccountPartialReconcileSynchronizer(self.odoo, self.db)
    
    def _acquire_lock(self, tenant_id: str) -> bool:
        """
         Acquire a lock to prevent concurrent syncs for the same tenant.
         In production, this should ideally use a distributed lock (Redis) or 
         a database-level lock.
         """
        query = "UPDATE tenants SET sync_status = 'syncing' WHERE id = %s AND sync_status != 'syncing'"
        self.db.execute(query, (tenant_id,))
        return self.db.cursor.rowcount > 0

    def _release_lock(self, tenant_id: str, status: str = 'active'):
        """Release the sync lock. Only update last_sync_at on successful sync."""
        if status == 'active':
            query = "UPDATE tenants SET sync_status = %s, last_sync_at = NOW() WHERE id = %s"
            self.db.execute(query, (status, tenant_id))
        else:
            query = "UPDATE tenants SET sync_status = %s WHERE id = %s"
            self.db.execute(query, (status, tenant_id))

    def run_full_sync(self) -> Dict[str, Any]:
        """
        Complete professional data load with locking and phased execution.
        """
        tenant_id = self.tenant_config.tenant_id
        logger.info(f"Starting professional full sync for tenant: {self.tenant_config.name}")
        
        results = {'status': 'started', 'phases': {}}
        
        try:
            self.db.connect()
            
            # 1. Acquire Lock
            if not self._acquire_lock(tenant_id):
                logger.warning(f"Sync already in progress for tenant {tenant_id}")
                return {'status': 'ignored', 'message': 'Sync already in progress'}

            # 2. Authenticate
            self.with_retry(self.odoo.authenticate)
            
            # 3. Phase 1: Core Dimensions
            # We clear cache before each phase to ensure freshness
            logger.info("=== Phase 1: Core Dimensions ===")
            dimension_syncs = [
                ('companies', 'res.company', self.company_sync),
                ('categories', 'product.category', self.category_sync),
                ('products', 'product.product', self.product_sync),
                ('partners', 'res.partner', self.partner_sync),
                ('users', 'res.users', self.user_sync),
                ('lots', 'stock.lot', self.lot_sync),
                ('currencies', 'res.currency', self.currency_sync),
                ('account_tags', 'account.account.tag', self.account_tag_sync),
                ('chart_of_accounts', 'account.account', self.chart_of_accounts_sync),
                ('currency_rates', 'res.currency.rate', self.currency_rate_sync),
                ('journals', 'account.journal', self.journal_sync)
            ]
            
            # Sync Time Dimension first (no odoo model)
            self.time_sync.sync(tenant_id)

            for key, odoo_model, sync_obj in dimension_syncs:
                sync_obj.clear_cache()
                log_id = self.db.log_sync_start(tenant_id, odoo_model, 'full')
                synced, failed = sync_obj.sync(tenant_id)
                results['phases'][key] = {'synced': synced, 'failed': failed}
                self.db.log_sync_completion(log_id, synced, failed)
                logger.info(f"{key.capitalize()}: {synced} synced, {failed} failed")

            # 4. Phase 2: Transactional Data
            logger.info("=== Phase 2: Transactional Data ===")
            
            transactional_syncs = [
                ('sales_orders', 'sale.order', self.sales_order_sync),
                ('purchase_orders', 'purchase.order', self.purchase_order_sync),
                ('account_moves', 'account.move', self.account_move_sync),
                ('account_partial_reconciles', 'account.partial.reconcile', self.account_partial_reconcile_sync),
                ('bank_statements', 'account.bank.statement', self.bank_statement_sync),
                ('stock_pickings', 'stock.picking', self.picking_sync),
                ('stock_moves', 'stock.move', self.move_sync),
                ('stock_quants', 'stock.quant', self.quant_sync)
            ]
            
            for key, model, sync_obj in transactional_syncs:
                logger.info(f"Syncing {key}...")
                sync_obj.clear_cache()
                log_id = self.db.log_sync_start(tenant_id, model, 'full')
                synced, failed = sync_obj.sync(tenant_id)
                results['phases'][key] = {'synced': synced, 'failed': failed}
                self.db.log_sync_completion(log_id, synced, failed)
                logger.info(f"{key.capitalize()}: {synced} synced, {failed} failed")

            # 4.5. Backfill Account Types
            logger.info("=== Backfilling Account Types ===")
            self.account_move_sync.backfill_account_types(tenant_id)
            
            # 5. Release Lock (Success)
            self._release_lock(tenant_id, 'active')
            results['status'] = 'completed'
            
        except Exception as e:
            logger.error(f"Full sync failed for tenant {tenant_id}: {str(e)}")
            self._release_lock(tenant_id, 'error')
            results['status'] = 'failed'
            results['error'] = str(e)
            raise
        finally:
            self.db.close()
            
        return results

    def run_delta_sync(self) -> Dict[str, Any]:
        """
        Professional incremental sync for ALL modules.
        Fetches only data modified since the last successful sync.
        """
        tenant_id = self.tenant_config.tenant_id
        logger.info(f"Starting professional delta sync for tenant: {self.tenant_config.name}")
        
        results = {'status': 'started', 'phases': {}}
        
        try:
            self.db.connect()
            
            if not self._acquire_lock(tenant_id):
                return {'status': 'ignored', 'message': 'Sync already in progress'}

            self.with_retry(self.odoo.authenticate)
            
            # 1. Dimension Delta (Categories, Products, Partners, Users, Lots)
            # Companies is usually small, so sync full is fine, but we'll include it.
            dimension_targets = [
                ('companies', 'res.company', self.company_sync),
                ('categories', 'product.category', self.category_sync),
                ('products', 'product.product', self.product_sync),
                ('partners', 'res.partner', self.partner_sync),
                ('users', 'res.users', self.user_sync),
                ('lots', 'stock.lot', self.lot_sync),
                ('currencies', 'res.currency', self.currency_sync),
                ('account_tags', 'account.account.tag', self.account_tag_sync),
                ('chart_of_accounts', 'account.account', self.chart_of_accounts_sync),
                ('currency_rates', 'res.currency.rate', self.currency_rate_sync),
                ('journals', 'account.journal', self.journal_sync),
            ]

            logger.info("--- Phase 1: Dimension Delta ---")
            for key, odoo_model, sync_obj in dimension_targets:
                last_sync = self.db.get_last_sync_time(tenant_id, odoo_model)
                logger.debug(f"Last sync for {key}: {last_sync}")
                
                sync_obj.clear_cache()
                log_id = self.db.log_sync_start(tenant_id, odoo_model, 'delta' if last_sync else 'full')
                synced, failed = sync_obj.sync(tenant_id, last_sync_date=last_sync)
                results['phases'][key] = {'synced': synced, 'failed': failed, 'type': 'delta' if last_sync else 'full'}
                self.db.log_sync_completion(log_id, synced, failed)

            # 2. Transactional Data Delta
            logger.info("--- Phase 2: Transactional Delta ---")
            delta_targets = [
                ('sales_orders', 'sale.order', self.sales_order_sync),
                ('purchase_orders', 'purchase.order', self.purchase_order_sync),
                ('account_moves', 'account.move', self.account_move_sync),
                ('account_partial_reconciles', 'account.partial.reconcile', self.account_partial_reconcile_sync),
                ('bank_statements', 'account.bank.statement', self.bank_statement_sync),
                ('stock_pickings', 'stock.picking', self.picking_sync),
                ('stock_moves', 'stock.move', self.move_sync)
            ]
            
            for key, model, sync_obj in delta_targets:
                last_sync = self.db.get_last_sync_time(tenant_id, model)
                if last_sync:
                    logger.info(f"Syncing {key} since: {last_sync}")
                    sync_obj.clear_cache()
                    log_id = self.db.log_sync_start(tenant_id, model, 'delta')
                    synced, failed = sync_obj.sync(tenant_id, last_sync_date=last_sync)
                    results['phases'][key] = {'synced': synced, 'failed': failed, 'type': 'delta'}
                    self.db.log_sync_completion(log_id, synced, failed)
                else:
                    logger.info(f"First time sync for {key}, performing full load...")
                    sync_obj.clear_cache()
                    log_id = self.db.log_sync_start(tenant_id, model, 'full')
                    synced, failed = sync_obj.sync(tenant_id)
                    results['phases'][key] = {'synced': synced, 'failed': failed, 'type': 'full'}
                    self.db.log_sync_completion(log_id, synced, failed)

            # 2.5 Backfill Account Types for any new lines that missed it
            logger.info("--- Backfilling Account Types ---")
            self.account_move_sync.backfill_account_types(tenant_id)

            # 3. Always sync quants in full as they are state, not transactions
            logger.info("--- Phase 3: Inventory State ---")
            self.quant_sync.clear_cache()
            synced, failed = self.quant_sync.sync(tenant_id)
            results['phases']['stock_quants'] = {'synced': synced, 'failed': failed, 'type': 'full'}

            self._release_lock(tenant_id, 'active')
            results['status'] = 'completed'
            
        except Exception as e:
            logger.error(f"Delta sync failed for tenant {tenant_id}: {str(e)}")
            self._release_lock(tenant_id, 'error')
            results['status'] = 'failed'
            results['error'] = str(e)
            raise
        finally:
            self.db.close()
            
        return results

    def run_smart_sync(self) -> Dict[str, Any]:
        """
        Intelligent sync selector.
        If no history exists for core dimensions, runs full sync.
        Otherwise runs robust delta sync.
        """
        tenant_id = self.tenant_config.tenant_id
        
        # Check if we have synced products before
        try:
            self.db.connect()
            last_product_sync = self.db.get_last_sync_time(tenant_id, 'product.product')
            self.db.close()
            
            if not last_product_sync:
                logger.info("No history found. Triggering full sync...")
                return self.run_full_sync()
            else:
                logger.info("History exists. Triggering smart incremental sync...")
                return self.run_delta_sync()
        except Exception as e:
            logger.error(f"Smart sync decision failed: {e}")
            return self.run_delta_sync() # Fallback to delta which handles no-history anyway

    def with_retry(self, func, max_retries=3):
        """Generic retry wrapper for orchestrator-level operations"""
        import time
        for i in range(max_retries):
            try:
                return func()
            except Exception as e:
                if i == max_retries - 1: raise
                logger.warning(f"Orchestrator retry {i+1} due to: {e}")
                time.sleep(1)
    
    def get_sync_status(self) -> Dict[str, any]:
        """
        Get status of last syncs for all modules
        
        Returns:
            Dictionary with last sync info
        """
        try:
            self.db.connect()
            
            tenant_id = self.tenant_config.tenant_id
            
            query = """
                SELECT entity_type, status, records_synced, records_failed, completed_at
                FROM sync_logs
                WHERE tenant_id = %s
                ORDER BY completed_at DESC
                LIMIT 1
            """
            
            result = self.db.fetch_one(query, (tenant_id,))
            
            if result:
                return {
                    'entity_type': result[0],
                    'status': result[1],
                    'records_synced': result[2],
                    'records_failed': result[3],
                    'last_sync': result[4]
                }
            else:
                return {'status': 'No sync history'}
            
        finally:
            self.db.close()
