"""
Custom exception handler for FastAPI
"""

from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from doova_one_view.api.common.exceptions import APIException


async def api_exception_handler(request: Request, exc: APIException) -> JSONResponse:
    """Handle custom API exceptions"""
    # Extract clean message without status code
    message = str(exc.detail) if hasattr(exc, 'detail') else str(exc.message)
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "message": message,
            "message_type": getattr(exc, 'message_type', 'error')
        }
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Handle standard HTTP exceptions"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "message": str(exc.detail),
            "message_type": "error"
        }
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle validation errors"""
    import logging
    logger = logging.getLogger("fastapi")
    logger.error(f"❌ VALIDATION ERROR: {exc.errors()}")
    logger.error(f"📦 BODY: {exc.body}")
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "message": "Validation error",
            "details": exc.errors(),
            "message_type": "error"
        }
    )
