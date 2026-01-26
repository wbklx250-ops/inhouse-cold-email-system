import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.routes import domains_router, mailboxes_router, tenants_router, wizard_router, stats_router
from app.core.config import get_settings
from app.db.session import engine
from app.services.powershell.setup import ensure_powershell_modules, check_powershell_available
from app.services.background_jobs import start_background_scheduler, stop_background_scheduler

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup: Test database connection
    logger.info("Testing database connection...")
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection successful")
    except Exception as e:
        logger.error("Database connection failed: %s", e)
        raise

    # Startup: Ensure PowerShell modules are installed (for M365 automation)
    logger.info("Checking PowerShell environment...")
    if check_powershell_available():
        if ensure_powershell_modules():
            logger.info("PowerShell environment ready - M365 automation enabled")
        else:
            logger.error("Failed to setup PowerShell modules - M365 automation will not work")
    else:
        logger.warning("PowerShell not available - M365 automation will not work")

    # Startup: Start background job scheduler (DKIM retry, etc.)
    logger.info("Starting background job scheduler...")
    start_background_scheduler()

    yield

    # Shutdown: Stop background scheduler
    logger.info("Stopping background job scheduler...")
    stop_background_scheduler()

    # Shutdown: Dispose engine
    await engine.dispose()
    logger.info("Database connection closed")


app = FastAPI(
    title="Cold Email Infrastructure API",
    version="1.0.0",
    description="API for managing cold email infrastructure: domains, tenants, and mailboxes",
    lifespan=lifespan,
    redirect_slashes=False,
)

# CORS configuration - allow frontend
allowed_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
# Add any additional origins from settings
if settings.allowed_origins:
    allowed_origins.extend([str(origin) for origin in settings.allowed_origins])

# In debug mode, allow all origins for easier development
if settings.debug:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# Register routers
app.include_router(domains_router)
app.include_router(mailboxes_router)
app.include_router(tenants_router)
app.include_router(wizard_router)
app.include_router(stats_router)


@app.get("/", tags=["root"])
async def root() -> dict[str, Any]:
    """Root endpoint with API information."""
    return {
        "name": "Cold Email Infrastructure API",
        "version": "1.0.0",
        "description": "Manage domains, tenants, and mailboxes for cold email infrastructure",
        "endpoints": {
            "domains": "/api/v1/domains",
            "tenants": "/api/v1/tenants",
            "mailboxes": "/api/v1/mailboxes",
            "health": "/health",
            "docs": "/docs",
        },
    }


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}