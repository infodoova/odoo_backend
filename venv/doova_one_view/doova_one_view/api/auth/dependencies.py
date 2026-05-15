"""
Authentication-specific dependencies
"""

from doova_one_view.api.dependencies import get_current_user

# Re-export for convenience
__all__ = ["get_current_user"]
