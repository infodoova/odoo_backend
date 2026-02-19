"""
Doova OneView - ETL Module
Complete ETL pipeline for Odoo data synchronization
"""

from odoo_app.etl.config import TenantConfig, SyncConfig
from odoo_app.etl.clients.odoo_client import OdooClient
from odoo_app.etl.managers.database_manager import DatabaseManager
from odoo_app.etl.transformers.data_transformer import DataTransformer
from odoo_app.etl.orchestrator import ETLOrchestrator

__all__ = [
    'TenantConfig',
    'SyncConfig',
    'OdooClient',
    'DatabaseManager',
    'DataTransformer',
    'ETLOrchestrator',
]

__version__ = '1.0.0'
