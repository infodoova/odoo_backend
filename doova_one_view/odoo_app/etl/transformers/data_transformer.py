"""
Data transformation utilities
Converts Odoo data types to unified schema format
"""

from datetime import datetime
from typing import Optional, Union, Tuple, List, Any


class DataTransformer:
    """Transform Odoo data to unified schema format"""
    
    @staticmethod
    def parse_odoo_many2one(field_value: Any) -> Optional[int]:
        """
        Odoo Many2one fields return tuple: (id, name) or False
        Extract just the ID
        
        Args:
            field_value: Odoo many2one field value
        
        Returns:
            ID (int) or None
        """
        if not field_value or field_value is False:
            return None
        if isinstance(field_value, (list, tuple)) and len(field_value) > 0:
            return field_value[0]
        return None
    
    @staticmethod
    def parse_odoo_one2many(field_value: Any) -> List[int]:
        """
        Odoo One2many fields return list of IDs
        
        Args:
            field_value: Odoo one2many field value
        
        Returns:
            List of IDs
        """
        if not field_value:
            return []
        if isinstance(field_value, (list, tuple)):
            return list(field_value)
        return []
    
    @staticmethod
    def parse_odoo_datetime(dt_string: str) -> Optional[str]:
        """
        Convert Odoo datetime string to PostgreSQL ISO format
        
        Args:
            dt_string: Odoo datetime string (format: 'YYYY-MM-DD HH:MM:SS')
        
        Returns:
            ISO format datetime string or None
        """
        if not dt_string:
            return None
        try:
            dt = datetime.strptime(dt_string, '%Y-%m-%d %H:%M:%S')
            return dt.isoformat()
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def parse_odoo_date(date_string: str) -> Optional[str]:
        """
        Convert Odoo date string to PostgreSQL ISO format
        
        Args:
            date_string: Odoo date string (format: 'YYYY-MM-DD')
        
        Returns:
            ISO format date string or None
        """
        if not date_string:
            return None
        try:
            # Already in ISO format
            datetime.strptime(date_string, '%Y-%m-%d')
            return date_string
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def get_date_id(date_string: str) -> Optional[int]:
        """
        Convert date to date_id (YYYYMMDD integer format)
        
        Args:
            date_string: Date string (can be full datetime or date)
        
        Returns:
            Integer date_id (YYYYMMDD) or None
        """
        if not date_string:
            return None
        try:
            dt = datetime.strptime(date_string[:10], '%Y-%m-%d')
            return int(dt.strftime('%Y%m%d'))
        except (ValueError, TypeError, IndexError):
            return None
    
    @staticmethod
    def parse_odoo_float(value: Any, decimal_places: int = 2) -> Optional[float]:
        """
        Parse Odoo float value and round to decimal places
        
        Args:
            value: Float value from Odoo
            decimal_places: Number of decimal places to round to
        
        Returns:
            Rounded float or None
        """
        if value is None or value is False:
            return None
        try:
            return round(float(value), decimal_places)
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def parse_odoo_boolean(value: Any) -> bool:
        """
        Parse Odoo boolean value
        
        Args:
            value: Boolean value from Odoo
        
        Returns:
            Boolean
        """
        if value is None or value is False:
            return False
        return bool(value)
    
    @staticmethod
    def parse_odoo_string(value: Any, max_length: int = None) -> Optional[str]:
        """
        Parse Odoo string value
        
        Args:
            value: String value from Odoo
            max_length: Maximum length to truncate to
        
        Returns:
            String or None
        """
        if not value:
            return None
        
        string_val = str(value).strip()
        
        if not string_val:
            return None
        
        if max_length and len(string_val) > max_length:
            string_val = string_val[:max_length]
        
        return string_val
    
    @staticmethod
    def parse_odoo_decimal(value: Any, decimal_places: int = 2) -> Optional[str]:
        """
        Parse Odoo decimal value for PostgreSQL NUMERIC type
        
        Args:
            value: Decimal value from Odoo
            decimal_places: Number of decimal places
        
        Returns:
            Decimal string or None
        """
        if value is None or value is False:
            return None
        try:
            float_val = float(value)
            return str(round(float_val, decimal_places))
        except (ValueError, TypeError):
            return None
