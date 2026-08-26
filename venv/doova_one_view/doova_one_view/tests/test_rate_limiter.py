# doova_one_view/tests/test_rate_limiter.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
from unittest.mock import MagicMock, patch
from doova_one_view.api.middleware import RateLimiter, rate_limit_middleware
from fastapi import Request
import asyncio

class TestRateLimiterMiddleware(unittest.TestCase):

    def setUp(self):
        self.limiter = RateLimiter(requests_per_minute=3)

    def test_rate_limiter_sliding_window_allowed_and_blocked(self):
        """Verify RateLimiter permits up to RPM requests and blocks subsequent requests."""
        client_key = "192.168.1.100"

        # First 3 requests allowed
        for i in range(3):
            allowed, remaining, reset_sec = self.limiter.is_allowed(client_key)
            self.assertTrue(allowed, f"Request {i+1} should be allowed")

        # 4th request blocked
        allowed, remaining, reset_sec = self.limiter.is_allowed(client_key)
        self.assertFalse(allowed, "4th request should be blocked")
        self.assertEqual(remaining, 0)
        self.assertGreater(reset_sec, 0)

    def test_rate_limiter_reset(self):
        """Verify RateLimiter reset clears counters."""
        client_key = "192.168.1.101"
        for _ in range(3):
            self.limiter.is_allowed(client_key)

        allowed_before, _, _ = self.limiter.is_allowed(client_key)
        self.assertFalse(allowed_before)

        self.limiter.reset()

        allowed_after, remaining, _ = self.limiter.is_allowed(client_key)
        self.assertTrue(allowed_after)
        self.assertEqual(remaining, 2)

    def test_rate_limit_middleware_ignores_non_agent_paths(self):
        """Verify non-financial-advisor endpoints bypass agent rate limiter."""
        request = MagicMock(spec=Request)
        request.url.path = "/api/v1/sales/orders"
        
        async def call_next(req):
            response = MagicMock()
            response.headers = {}
            return response

        response = asyncio.run(rate_limit_middleware(request, call_next))
        self.assertNotIn("X-RateLimit-Limit", response.headers)

if __name__ == "__main__":
    unittest.main()
