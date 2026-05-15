"""
ETL Module Documentation and Usage Guide

ARCHITECTURE OVERVIEW
=====================

The ETL module is designed following SOLID principles with clear separation of concerns:

1. **Config Layer** (config.py)
   - TenantConfig: Odoo instance configuration
   - SyncConfig: Sync job parameters

2. **Client Layer** (clients/odoo_client.py)
   - OdooClient: JSON-RPC 2.0 API client for Odoo
   - Handles authentication and all API calls

3. **Manager Layer** (managers/database_manager.py)
   - DatabaseManager: PostgreSQL connection and operations
   - Wraps psycopg2 with clean interface

4. **Transformer Layer** (transformers/data_transformer.py)
   - DataTransformer: Converts Odoo data types to PostgreSQL formats
   - Handles Odoo-specific data like Many2one fields

5. **Synchronizer Layer** (syncs/)
   - BaseSynchronizer: Abstract base with common operations
   - DimensionSynchronizers: Companies, Products, Categories, Partners, Users
   - SalesOrderSynchronizer: Sales orders and lines
   - Extensible for Accounting, Inventory, Purchasing modules

6. **Orchestrator Layer** (orchestrator.py)
   - ETLOrchestrator: Coordinates all sync operations
   - Manages full sync, delta sync, and status checking

USAGE EXAMPLES
==============

1. Full Initial Sync (from Django management command):
   python manage.py sync_odoo full --tenant-id <uuid>

2. Incremental Delta Sync:
   python manage.py sync_odoo delta --tenant-id <uuid>

3. Check Sync Status:
   python manage.py sync_odoo status --tenant-id <uuid>

4. Direct Python Usage:
   from odoo_app.etl import TenantConfig, ETLOrchestrator
   
   tenant = TenantConfig(
       tenant_id="uuid",
       name="Company Name",
       odoo_url="https://company.odoo.com",
       odoo_database="company_db",
       odoo_username="user@company.com",
       odoo_api_key="api_key"
   )
   
   db_conn = "host=localhost dbname=unified user=user password=pass"
   orchestrator = ETLOrchestrator(tenant, db_conn)
   
   # Run sync
   results = orchestrator.run_full_sync()
   # or
   results = orchestrator.run_delta_sync()

EXTENDING THE MODULE
====================

To add a new sync module (e.g., AccountMove for invoices):

1. Create new file: syncs/accounting_synchronizer.py
2. Extend BaseSynchronizer:
   
   from .base_synchronizer import BaseSynchronizer
   
   class AccountMoveSynchronizer(BaseSynchronizer):
       def sync(self, tenant_id: str, **kwargs):
           # Implement sync logic
           pass

3. Add to ETLOrchestrator:
   from .syncs.accounting_synchronizer import AccountMoveSynchronizer
   
   def __init__(self, ...):
       ...
       self.account_move_sync = AccountMoveSynchronizer(self.odoo, self.db)

4. Create sync phase in run_full_sync():
   results['account_moves'] = self.account_move_sync.sync(tenant_id)

DATA FLOW
=========

Odoo Instance
    ↓
OdooClient (JSON-RPC 2.0 API)
    ↓
Raw Odoo Data (Many2one, Dates, Floats)
    ↓
DataTransformer (Converts to PostgreSQL types)
    ↓
Synchronizers (Insert/Update via DatabaseManager)
    ↓
PostgreSQL Database
    ↓
Analytics & Reports

BEST PRACTICES
==============

1. **Error Handling**: Each synchronizer returns (synced_count, failed_count)
2. **Logging**: Uses Python logging module (configure in settings.py)
3. **Batch Operations**: DatabaseManager supports batch inserts for performance
4. **Delta Sync**: Only syncs changed records using write_date field
5. **Abstraction**: New Odoo models can be synced without modifying core code
6. **Testing**: Each class can be tested independently

PERFORMANCE TIPS
================

1. Run delta sync frequently (every 15 minutes) instead of full sync
2. Use batch_size parameter in execute_batch for large datasets
3. Create database indexes on tenant_id + odoo_id for faster lookups
4. Consider running full sync at off-peak hours
5. Monitor sync logs in sync_logs table for performance analysis
"""
