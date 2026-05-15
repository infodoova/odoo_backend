"""
ETL Configuration classes
"""

from dataclasses import dataclass
from typing import List


@dataclass
class TenantConfig:
    """Configuration for one Odoo tenant"""
    tenant_id: str
    name: str
    odoo_url: str
    odoo_database: str
    odoo_username: str
    odoo_api_key: str


@dataclass
class SyncConfig:
    """Sync job configuration"""
    entity_type: str
    odoo_model: str
    fields: List[str]
    batch_size: int = 100
    full_sync: bool = False
