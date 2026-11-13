"""
Custom middleware for FastAPI including logging and Rate Limiting for Financial Advisor Agent
"""

from fastapi import Request, status
from fastapi.responses import JSONResponse
import hashlib
import logging
import time
from collections import defaultdict
from threading import Lock

logger = logging.getLogger(__name__)


class RateLimiter:
    """Sliding-window rate limiter per client IP / tenant."""
    # Upper bound on tracked keys so a client cannot grow memory by inventing identities.
    MAX_KEYS = 20_000

    def __init__(self, requests_per_minute: int = 30):
        self.rpm = requests_per_minute
        self.requests = defaultdict(list)
        self.lock = Lock()

    def _prune(self, now: float) -> None:
        """Drop keys with no request in the last minute (called with the lock held)."""
        window_start = now - 60.0
        for key in [k for k, ts in self.requests.items() if not ts or ts[-1] <= window_start]:
            del self.requests[key]

    def is_allowed(self, key: str) -> tuple[bool, int, int]:
        """
        Returns (allowed: bool, remaining_requests: int, reset_seconds: int)
        """
        now = time.time()
        window_start = now - 60.0
        with self.lock:
            if len(self.requests) >= self.MAX_KEYS:
                self._prune(now)
            # Clean up timestamps older than 60 seconds
            timestamps = [t for t in self.requests[key] if t > window_start]
            self.requests[key] = timestamps
            
            if len(timestamps) < self.rpm:
                timestamps.append(now)
                remaining = self.rpm - len(timestamps)
                reset_seconds = int(60 - (now - timestamps[0])) if timestamps else 60
                return True, remaining, max(1, reset_seconds)
            else:
                remaining = 0
                reset_seconds = int(60 - (now - timestamps[0])) if timestamps else 60
                return False, remaining, max(1, reset_seconds)

    def reset(self):
        """Reset all rate limiter counters (useful for unit testing)."""
        with self.lock:
            self.requests.clear()


# Generative calls (chat / reasoning execution)
agent_chat_rate_limiter = RateLimiter(requests_per_minute=120)
# Read-only calls (sessions list, history, stats, reports preview)
agent_read_rate_limiter = RateLimiter(requests_per_minute=600)
# Alias for backwards compatibility
agent_rate_limiter = agent_chat_rate_limiter


async def rate_limit_middleware(request: Request, call_next):
    """Rate-limiting middleware for /financial-advisor agent endpoints."""
    path = request.url.path
    if "/financial-advisor" in path:
        # The key must be something the client cannot vary at will: a digest of the whole
        # credential (so the limit follows the account, not a header value), or the network
        # address when there is none. Request headers such as X-Tenant-Id are not part of it.
        auth_header = request.headers.get("Authorization", "")
        client_ip = request.client.host if request.client else "unknown_client"

        if auth_header:
            client_key = "tok:" + hashlib.sha256(auth_header.encode("utf-8")).hexdigest()[:24]
        else:
            client_key = f"ip:{client_ip}"

        # Use separate limiters for heavy POST (chat) vs lightweight GET (sessions, history)
        is_write = request.method in ("POST", "PUT", "DELETE", "PATCH")
        limiter = agent_chat_rate_limiter if is_write else agent_read_rate_limiter
        
        allowed, remaining, reset_sec = limiter.is_allowed(client_key)
        
        if not allowed:
            logger.warning(f"Rate limit exceeded ({request.method}) for client {client_key} on {path}")
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Rate limit exceeded for Financial Advisor Agent. Please wait a moment before sending more requests."},
                headers={
                    "X-RateLimit-Limit": str(limiter.rpm),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_sec),
                    "Retry-After": str(reset_sec)
                }
            )
            
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limiter.rpm)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_sec)
        return response

    return await call_next(request)


async def logging_middleware(request: Request, call_next):
    """Log all requests"""
    start_time = time.time()
    
    # Log request
    logger.info(
        f"{request.method} {request.url.path} - "
        f"Client: {request.client.host if request.client else 'unknown'}"
    )
    
    try:
        response = await call_next(request)
        
        # Log response
        process_time = time.time() - start_time
        logger.info(
            f"{request.method} {request.url.path} - "
            f"Status: {response.status_code} - "
            f"Time: {process_time:.3f}s"
        )
        
        return response
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"}
        )
    finally:
        # Cleanup Django database connections opened in the main async thread
        from django.db import connections
        connections.close_all()
