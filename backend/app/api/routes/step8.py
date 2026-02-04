"""
Step 8 API Routes - Disable Security Defaults
==============================================

API endpoints to disable Security Defaults on M365 tenants.
This must be done BEFORE OAuth authentication with email sequencers
(PlusVibe, Smartlead, Instantly) will work.
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.db.session import get_db_session
from app.services.step8_security_defaults import (
    SecurityDefaultsDisabler,
    TenantCredentials
)
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/step8", tags=["Step 8 - Security Defaults"])


@router.post("/disable/{tenant_id}")
async def disable_security_defaults_single(
    tenant_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session)
):
    """Disable Security Defaults for a single tenant."""
    
    # Fetch tenant credentials
    query = text("""
        SELECT 
            t.id,
            t.admin_email,
            t.admin_password,
            t.totp_secret,
            d.name as domain
        FROM tenants t
        JOIN domains d ON t.domain_id = d.id
        WHERE t.id = :tenant_id
    """)
    result = await db.execute(query, {"tenant_id": tenant_id})
    row = result.fetchone()
    
    if not row:
        raise HTTPException(404, "Tenant not found")
    
    if not row.totp_secret:
        raise HTTPException(400, "Tenant missing TOTP secret - run Step 5 first")
    
    if not row.admin_password:
        raise HTTPException(400, "Tenant missing admin password")
    
    # Run synchronously for now (can move to background task later)
    creds = TenantCredentials(
        tenant_id=str(row.id),
        domain=row.domain,
        admin_email=row.admin_email,
        admin_password=row.admin_password,
        totp_secret=row.totp_secret
    )
    
    disabler = SecurityDefaultsDisabler(headless=True, worker_id=0)
    result = disabler.disable_for_tenant(creds)
    
    # Update database
    if result['success']:
        await db.execute(text("""
            UPDATE tenants SET 
                security_defaults_disabled = true,
                security_defaults_error = NULL,
                security_defaults_disabled_at = NOW()
            WHERE id = :tenant_id
        """), {"tenant_id": tenant_id})
    else:
        await db.execute(text("""
            UPDATE tenants SET 
                security_defaults_disabled = false,
                security_defaults_error = :error
            WHERE id = :tenant_id
        """), {"tenant_id": tenant_id, "error": result.get('error')})
    
    await db.commit()
    
    return {
        "tenant_id": tenant_id,
        "domain": row.domain,
        "success": result['success'],
        "error": result.get('error')
    }


@router.post("/disable-batch")
async def disable_security_defaults_batch(
    batch_size: int = 10,
    db: AsyncSession = Depends(get_db_session)
):
    """Disable Security Defaults for a batch of tenants that need it."""
    
    # Get tenants that need Security Defaults disabled
    query = text("""
        SELECT 
            t.id,
            t.admin_email,
            t.admin_password,
            t.totp_secret,
            d.name as domain
        FROM tenants t
        JOIN domains d ON t.domain_id = d.id
        WHERE t.security_defaults_disabled = false
        AND t.totp_secret IS NOT NULL
        AND t.admin_password IS NOT NULL
        ORDER BY t.created_at
        LIMIT :batch_size
    """)
    result = await db.execute(query, {"batch_size": batch_size})
    rows = result.fetchall()
    
    if not rows:
        return {"message": "No tenants need Security Defaults disabled", "processed": 0}
    
    # Convert to credentials
    tenants = []
    for row in rows:
        tenants.append(TenantCredentials(
            tenant_id=str(row.id),
            domain=row.domain,
            admin_email=row.admin_email,
            admin_password=row.admin_password,
            totp_secret=row.totp_secret
        ))
    
    # Process batch
    disabler = SecurityDefaultsDisabler(headless=True, worker_id=0)
    summary = disabler.disable_for_batch(tenants)
    
    # Update database for each result
    for res in summary['results']:
        tenant_id = res.get('tenant_id') or next(
            (t.tenant_id for t in tenants if t.domain == res['domain']), None
        )
        if tenant_id:
            if res['success']:
                await db.execute(text("""
                    UPDATE tenants SET 
                        security_defaults_disabled = true,
                        security_defaults_error = NULL,
                        security_defaults_disabled_at = NOW()
                    WHERE id = :tenant_id
                """), {"tenant_id": int(tenant_id)})
            else:
                await db.execute(text("""
                    UPDATE tenants SET 
                        security_defaults_error = :error
                    WHERE id = :tenant_id
                """), {"tenant_id": int(tenant_id), "error": res.get('error')})
    
    await db.commit()
    
    return summary


@router.get("/status")
async def get_security_defaults_status(db: AsyncSession = Depends(get_db_session)):
    """Get count of tenants by Security Defaults status."""
    
    query = text("""
        SELECT 
            COUNT(*) FILTER (WHERE security_defaults_disabled = true) as disabled,
            COUNT(*) FILTER (WHERE security_defaults_disabled = false AND totp_secret IS NOT NULL) as pending,
            COUNT(*) FILTER (WHERE totp_secret IS NULL) as not_ready
        FROM tenants
    """)
    result = await db.execute(query)
    row = result.fetchone()
    
    return {
        "disabled": row.disabled or 0,
        "pending": row.pending or 0,
        "not_ready": row.not_ready or 0
    }
