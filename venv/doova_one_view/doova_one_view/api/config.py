"""
API configuration
"""

from typing import List
from django.conf import settings as django_settings


class APISettings:
    """API configuration settings"""
    
    def __init__(self):
        # CORS settings - can be overridden via Django settings
        self.cors_origins = getattr(
            django_settings,
            'API_CORS_ORIGINS',
            ["*"]
        )
        self.cors_allow_credentials = getattr(
            django_settings,
            'API_CORS_ALLOW_CREDENTIALS',
            True
        )
        self.cors_allow_methods = getattr(
            django_settings,
            'API_CORS_ALLOW_METHODS',
            ["*"]
        )
        self.cors_allow_headers = getattr(
            django_settings,
            'API_CORS_ALLOW_HEADERS',
            ["*"]
        )
        
        # API settings
        self.api_title = getattr(
            django_settings,
            'API_TITLE',
            "Doova One View API"
        )
        self.api_version = getattr(
            django_settings,
            'API_VERSION',
            "1.0.0"
        )
        self.api_description = getattr(
            django_settings,
            'API_DESCRIPTION',
            "Multi-tenant Odoo integration platform API"
        )
        
        # Rate limiting
        self.rate_limit_enabled = getattr(
            django_settings,
            'API_RATE_LIMIT_ENABLED',
            False
        )
        self.rate_limit_per_minute = getattr(
            django_settings,
            'API_RATE_LIMIT_PER_MINUTE',
            60
        )
        
        # Sync Job Settings
        self.sync_interval_minutes = getattr(
            django_settings,
            'SYNC_INTERVAL_MINUTES',
            30
        )


# Global settings instance
settings = APISettings()
