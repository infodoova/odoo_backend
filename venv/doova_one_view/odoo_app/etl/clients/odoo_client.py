"""
Odoo JSON-RPC 2.0 API Client
"""

import requests
import json
import logging
import random
from typing import List, Dict, Optional, Any
from odoo_app.etl.config import TenantConfig

logger = logging.getLogger(__name__)


class OdooClient:
    """
    Odoo JSON-RPC 2.0 API Client
    
    Uses the /jsonrpc endpoint for all API calls targeting
    the 'common' and 'object' services. This approach is 
    fully compatible with Odoo API Keys.
    """
    
    def __init__(self, config: TenantConfig, timeout: int = 60):
        self.config = config
        self.url = config.odoo_url.rstrip('/')
        self.db = config.odoo_database
        self.username = config.odoo_username
        self.api_key = config.odoo_api_key
        self.uid = None
        self.timeout = timeout
        
        # HTTP session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'DoovaOneView-ETL/1.0'
        })
        
        logger.info(f"Initialized Odoo JSON-RPC client for {config.name}")
    
    def _call_rpc(self, service: str, method: str, args: List) -> Any:
        """
        Make a JSON-RPC 2.0 call to Odoo via the /jsonrpc endpoint
        """
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": service,
                "method": method,
                "args": args
            },
            "id": self._generate_request_id()
        }
        
        url = f"{self.url}/jsonrpc"
        
        try:
            response = self.session.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            
            result = response.json()
            
            if 'error' in result:
                error = result['error']
                error_msg = error.get('data', {}).get('message', error.get('message', 'Unknown error'))
                logger.error(f"Odoo RPC Error in {service}.{method}: {error_msg}")
                raise Exception(f"Odoo RPC Error: {error_msg}")
            
            return result.get('result')
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Odoo HTTP failure: {e}")
            raise
        except Exception as e:
            logger.error(f"Odoo RPC failure: {e}")
            raise

    @staticmethod
    def _generate_request_id() -> int:
        """Generate unique request ID"""
        return random.randint(1, 1000000)
    
    def authenticate(self) -> int:
        """
        Authenticate with Odoo and get user ID
        
        Returns:
            User ID (uid)
            
        Raises:
            Exception: If authentication fails
        """
        try:
            # common.authenticate(db, login, password, {})
            args = [self.db, self.username, self.api_key, {}]
            
            result = self._call_rpc('common', 'authenticate', args)
            
            if result:
                self.uid = result
                logger.info(f"Authenticated successfully. UID: {self.uid}")
                return self.uid
            else:
                raise Exception("Authentication failed: Invalid credentials or database name")
                
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            raise
    
    def call_kw(
        self, 
        model: str, 
        method: str, 
        args: List = None, 
        kwargs: Dict = None
    ) -> Any:
        """
        Call a model method using execute_kw via the 'object' service
        
        Args:
            model: Odoo model name (e.g., 'sale.order')
            method: Method name (e.g., 'search_read')
            args: Positional arguments
            kwargs: Keyword arguments
        
        Returns:
            Method result
        """
        if not self.uid:
            self.authenticate()
        
        args = args or []
        kwargs = kwargs or {}
        
        # Add authentication context if not present
        if "context" not in kwargs:
            kwargs["context"] = {}
        
        # object.execute_kw(db, uid, password, model, method, args, kwargs)
        rpc_args = [self.db, self.uid, self.api_key, model, method, args, kwargs]
        
        result = self._call_rpc('object', 'execute_kw', rpc_args)
        
        return result
    
    def search_read(
        self, 
        model: str, 
        domain: List = None,
        fields: List[str] = None,
        limit: int = None,
        offset: int = 0,
        order: str = None
    ) -> List[Dict]:
        """
        Search and read records from Odoo
        
        Args:
            model: Odoo model name
            domain: Search filters [['field', 'operator', 'value']]
            fields: Fields to retrieve
            limit: Max records to fetch
            offset: Pagination offset
            order: Sort order (e.g., 'date_order desc')
        
        Returns:
            List of records as dictionaries
        """
        domain = domain or []
        fields = fields or []
        
        kwargs = {'fields': fields}
        if limit:
            kwargs['limit'] = limit
        if offset:
            kwargs['offset'] = offset
        if order:
            kwargs['order'] = order
        
        try:
            records = self.call_kw(
                model=model,
                method='search_read',
                args=[domain],
                kwargs=kwargs
            )
            
            if not isinstance(records, list):
                logger.warning(f"search_read on {model} returned non-list result: {records}")
                return []
                
            logger.info(f"Fetched {len(records)} records from {model}")
            return records
            
        except Exception as e:
            logger.error(f"Error fetching from {model}: {e}")
            raise
    
    def search(
        self, 
        model: str, 
        domain: List = None,
        limit: int = None,
        offset: int = 0,
        order: str = None
    ) -> List[int]:
        """
        Search for record IDs
        
        Args:
            model: Odoo model name
            domain: Search filters
            limit: Max records
            offset: Pagination offset
            order: Sort order
        
        Returns:
            List of record IDs
        """
        domain = domain or []
        
        kwargs = {}
        if limit:
            kwargs['limit'] = limit
        if offset:
            kwargs['offset'] = offset
        if order:
            kwargs['order'] = order
        
        ids = self.call_kw(
            model=model,
            method='search',
            args=[domain],
            kwargs=kwargs
        )
        
        return ids
    
    def read(
        self, 
        model: str, 
        ids: List[int], 
        fields: List[str] = None
    ) -> List[Dict]:
        """
        Read records by IDs
        
        Args:
            model: Odoo model name
            ids: List of record IDs
            fields: Fields to retrieve
        
        Returns:
            List of records
        """
        fields = fields or []
        
        records = self.call_kw(
            model=model,
            method='read',
            args=[ids],
            kwargs={'fields': fields}
        )
        
        return records
    
    def search_count(self, model: str, domain: List = None) -> int:
        """
        Count records matching domain
        
        Args:
            model: Odoo model name
            domain: Search filters
        
        Returns:
            Number of matching records
        """
        domain = domain or []
        
        count = self.call_kw(
            model=model,
            method='search_count',
            args=[domain]
        )
        
        return count
    
    def create(self, model: str, values: Dict) -> int:
        """
        Create a new record
        
        Args:
            model: Odoo model name
            values: Field values
        
        Returns:
            ID of created record
        """
        record_id = self.call_kw(
            model=model,
            method='create',
            args=[values]
        )
        
        return record_id
    
    def write(self, model: str, ids: List[int], values: Dict) -> bool:
        """
        Update existing records
        
        Args:
            model: Odoo model name
            ids: List of record IDs to update
            values: Field values to update
        
        Returns:
            True if successful
        """
        success = self.call_kw(
            model=model,
            method='write',
            args=[ids, values]
        )
        
        return success
    
    def unlink(self, model: str, ids: List[int]) -> bool:
        """
        Delete records
        
        Args:
            model: Odoo model name
            ids: List of record IDs to delete
        
        Returns:
            True if successful
        """
        success = self.call_kw(
            model=model,
            method='unlink',
            args=[ids]
        )
        
        return success
    
    def get_fields(self, model: str, attributes: List[str] = None) -> Dict:
        """
        Get model field definitions
        
        Args:
            model: Odoo model name
            attributes: Field attributes to retrieve
        
        Returns:
            Dictionary of field definitions
        """
        attributes = attributes or [
            'string', 'type', 'help', 'required', 'readonly'
        ]
        
        fields = self.call_kw(
            model=model,
            method='fields_get',
            kwargs={'attributes': attributes}
        )
        
        return fields
