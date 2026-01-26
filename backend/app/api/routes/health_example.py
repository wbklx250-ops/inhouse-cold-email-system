"""
Health Check Endpoint - Add this to your FastAPI app

This should be in backend/app/api/routes/health.py
or added directly to backend/app/main.py
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

# If using a separate router file:
router = APIRouter()


@router.get("/health")
async def health_check():
    """
    Basic health check endpoint.
    Railway uses this to verify the service is running.
    """
    return {
        "status": "healthy",
        "service": "cold-email-platform-api"
    }


@router.get("/health/db")
async def health_check_db(db: AsyncSession = Depends(get_db)):
    """
    Health check with database connectivity test.
    Use this for more thorough health checks.
    """
    try:
        # Test database connection
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "service": "cold-email-platform-api",
        "database": db_status
    }


# ===========================================
# Add to your main.py if not using router:
# ===========================================

"""
# In backend/app/main.py:

from fastapi import FastAPI
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Starting up Cold Email Platform API...")
    yield
    # Shutdown
    print("Shutting down...")

app = FastAPI(
    title="Cold Email Infrastructure Platform",
    description="Automated M365 tenant and mailbox management",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/health")
async def health():
    return {"status": "healthy"}

# Include your routers
# app.include_router(domains_router, prefix="/api/v1")
# app.include_router(tenants_router, prefix="/api/v1")
# etc.
"""
