"""
FastAPI application factory
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
import os
import django

# Setup Django before importing any models
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
django.setup()

from doova_one_view.api.config import settings
from doova_one_view.api.middleware import logging_middleware
from doova_one_view.api.auth.routes import router as auth_router
from doova_one_view.api.tenants.routes import router as tenant_router
from doova_one_view.api.sales.routes import router as sales_router
from doova_one_view.api.purchase.routes import router as purchase_router
from doova_one_view.api.accounting.routes import router as accounting_router
from doova_one_view.api.inventory.routes import router as inventory_router
from doova_one_view.api.master_data.routes import router as master_data_router
from doova_one_view.api.files.routes import router as files_router
from doova_one_view.api.kpi.routes import router as kpi_router
from doova_one_view.api.agent.routes import router as agent_router
from doova_one_view.api.rbac.routes import router as rbac_router
from doova_one_view.api.reports.routes import router as reports_router
from doova_one_view.api.jobs.sync_job import SyncJobManager
from doova_one_view.api.jobs.report_job import ReportJobManager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for FastAPI app"""
    logger.info("FastAPI application starting")
    
    await SyncJobManager.start()
    await ReportJobManager.start()

    yield

    await SyncJobManager.stop()
    await ReportJobManager.stop()
    logger.info("FastAPI application shutting down")


def create_app() -> FastAPI:
    """
    Create and configure FastAPI application
    
    Returns:
        FastAPI: Configured FastAPI application instance
    """
    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        description=settings.api_description,
        lifespan=lifespan
    )
    
    # Add middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )
    app.middleware("http")(logging_middleware)
    
    # Register exception handlers
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from doova_one_view.api.common.exceptions import APIException
    from doova_one_view.api.common.handlers import (
        api_exception_handler,
        http_exception_handler,
        validation_exception_handler
    )
    
    app.add_exception_handler(APIException, api_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    
    # Include routers (no prefix needed, ASGI mounts at /api/v1)
    app.include_router(auth_router)
    app.include_router(tenant_router)
    app.include_router(sales_router)
    app.include_router(purchase_router)
    app.include_router(accounting_router)
    app.include_router(inventory_router)
    app.include_router(master_data_router)
    app.include_router(files_router)
    app.include_router(kpi_router)
    app.include_router(agent_router)
    app.include_router(rbac_router)
    app.include_router(reports_router)
    
    # Health check endpoint
    @app.get("/health", tags=["Health"])
    async def health_check():
        """Health check endpoint"""
        return {
            "status": "healthy",
            "service": settings.api_title,
            "version": settings.api_version
        }
    
    return app


# Create app instance
app = create_app()
