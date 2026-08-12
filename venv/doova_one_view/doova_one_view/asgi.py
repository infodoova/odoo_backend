"""
    ASGI config for doova_one_view project.

    Mounts both Django and FastAPI applications on the same ASGI server:
    - FastAPI handles: /api/* (all API endpoints)
    - Django handles: /admin, /static, and everything else

    For more information on ASGI, see:
    https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/

    Run with:
        uvicorn doova_one_view.asgi:application --host 0.0.0.0 --port 8000
    """

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv()
from django.core.asgi import get_asgi_application
from django.conf import settings
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

# Initialize Django first (required for models, ORM, etc.)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'doova_one_view.settings')
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
django_asgi = get_asgi_application()

# Import FastAPI app after Django setup
from doova_one_view.api.app import app as fastapi_app
from doova_one_view.api.jobs.sync_job import SyncJobManager
from doova_one_view.api.jobs.report_job import ReportJobManager
from doova_one_view.api.jobs.alert_job import AlertJobManager
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    """Main application lifespan — the FastAPI sub-app lifespan is NOT called
    when mounted via Starlette Mount(), so all background jobs must be started here."""
    await SyncJobManager.start()
    await ReportJobManager.start()
    await AlertJobManager.start()
    yield
    await SyncJobManager.stop()
    await ReportJobManager.stop()
    await AlertJobManager.stop()

# ============================================================================
# Main Application - Uses Mount-based routing with static files
# ============================================================================

# Define routes: more specific first
routes = [
    Mount("/api/v1", app=fastapi_app),  # FastAPI handles all /api/* endpoints
]

# Add static files mounting
static_dir = Path(settings.STATIC_ROOT)
if static_dir.exists():
    routes.append(Mount("/static", StaticFiles(directory=str(static_dir)), name="static"))


# Mount Django at root (handles /admin and everything else)
routes.append(Mount("/", app=django_asgi))

# Create the application
application = Starlette(routes=routes, lifespan=lifespan)

