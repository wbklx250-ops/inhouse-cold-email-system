"""
Setup Wizard API - Batch-aware!

Provides a simplified step-by-step interface for the cold email setup process.
All endpoints now require a batch_id parameter for independent setup sessions.
"""

from datetime import datetime
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, BackgroundTasks, Response
from fastapi.responses import StreamingResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, text
from sqlalchemy.orm import selectinload
from typing import Optional, List
from pydantic import BaseModel
from uuid import UUID
import csv
import io
import logging

from app.db.session import get_db_session as get_db, async_engine, get_db_session_with_retry, RetryableSession, SessionLocal, async_session_factory
from app.services.tenant_import import tenant_import_service
from app.services.tenant_automation import process_tenants_parallel, get_progress
from app.services.domain_import import parse_domains_csv, DomainImportData
from app.models.batch import SetupBatch, BatchStatus
from app.models.domain import Domain, DomainStatus
from app.models.tenant import Tenant, TenantStatus
from app.models.mailbox import Mailbox, MailboxStatus
from app.services.cloudflare import cloudflare_service
from app.services.email_generator import generate_email_addresses
from app.services.m365_scripts import m365_scripts
from app.services.mailbox_scripts import mailbox_scripts
from app.services.orchestrator import process_batch, SetupConfig
from app.services.m365_setup import run_step5_for_batch, run_step5_for_tenant, Step5Result
from app.services.selenium.parallel_processor import run_parallel_step5, DomainTask
from app.services.selenium.admin_portal import get_all_progress as get_live_progress, clear_all_progress
from app.services.mailbox_setup import (
    run_step6_for_batch,
    get_all_progress as get_step6_all_progress,
    get_progress as get_step6_progress,
)

router = APIRouter(prefix="/api/v1/wizard", tags=["wizard"])

logger = logging.getLogger(__name__)

# Store active automation jobs
active_jobs = {}

# Store active Step 4 automation jobs (per batch)
step4_jobs = {}


# ============== SCHEMAS ==============

class WizardStatus(BaseModel):
    current_step: int
    step_name: str
    can_proceed: bool
    
    # Step 1: Domains
    domains_total: int
    domains_imported: bool
    
    # Step 2: Zones
    zones_created: int
    zones_pending: int
    
    # Step 3: Propagation & Redirects
    ns_propagated: int
    ns_pending: int
    redirects_configured: int
    
    # Step 4: Tenants
    tenants_total: int
    tenants_linked: int
    
    # Step 5: M365 & DKIM
    tenants_m365_verified: int
    tenants_dkim_enabled: int
    
    # Step 6: Mailboxes
    mailboxes_total: int
    mailboxes_pending: int
    mailboxes_ready: int

    class Config:
        from_attributes = True


class StepResult(BaseModel):
    success: bool
    message: str
    details: Optional[dict] = None


class BatchCreate(BaseModel):
    """Schema for creating a new batch."""
    name: str
    description: Optional[str] = None
    redirect_url: Optional[str] = None


class BatchResponse(BaseModel):
    """Schema for batch response."""
    id: UUID
    name: str
    description: Optional[str]
    current_step: int
    status: str
    redirect_url: Optional[str]
    created_at: str
    domains_count: int
    tenants_count: int
    mailboxes_count: int

    class Config:
        from_attributes = True


class BatchWizardStatus(BaseModel):
    """Status for a specific batch."""
    batch_id: UUID
    batch_name: str
    current_step: int
    step_name: str
    can_proceed: bool
    status: str
    
    # Counts
    domains_total: int
    zones_created: int
    zones_pending: int
    ns_propagated: int
    ns_pending: int
    redirects_configured: int
    tenants_total: int
    tenants_linked: int
    tenants_m365_verified: int
    tenants_dkim_enabled: int
    mailboxes_total: int
    mailboxes_pending: int
    mailboxes_ready: int

    class Config:
        from_attributes = True


# ============== BATCH MANAGEMENT ==============

@router.get("/batches", response_model=List[BatchResponse])
async def list_batches(db: AsyncSession = Depends(get_db)):
    """List all setup batches with summary counts."""
    result = await db.execute(select(SetupBatch).order_by(SetupBatch.created_at.desc()))
    batches = result.scalars().all()
    
    response = []
    for batch in batches:
        # Count related records
        domains_count = (await db.execute(
            select(func.count(Domain.id)).where(Domain.batch_id == batch.id)
        )).scalar() or 0
        
        tenants_count = (await db.execute(
            select(func.count(Tenant.id)).where(Tenant.batch_id == batch.id)
        )).scalar() or 0
        
        mailboxes_count = (await db.execute(
            select(func.count(Mailbox.id)).where(Mailbox.batch_id == batch.id)
        )).scalar() or 0
        
        response.append(BatchResponse(
            id=batch.id,
            name=batch.name,
            description=batch.description,
            current_step=batch.current_step,
            status=batch.status.value,
            redirect_url=batch.redirect_url,
            created_at=batch.created_at.isoformat(),
            domains_count=domains_count,
            tenants_count=tenants_count,
            mailboxes_count=mailboxes_count,
        ))
    
    return response


@router.post("/batches", response_model=BatchResponse)
async def create_batch(
    batch_data: BatchCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new setup batch."""
    batch = SetupBatch(
        name=batch_data.name,
        description=batch_data.description,
        redirect_url=batch_data.redirect_url,
        current_step=1,
        status=BatchStatus.ACTIVE,
    )
    db.add(batch)
    await db.commit()
    await db.refresh(batch)
    
    return BatchResponse(
        id=batch.id,
        name=batch.name,
        description=batch.description,
        current_step=batch.current_step,
        status=batch.status.value,
        redirect_url=batch.redirect_url,
        created_at=batch.created_at.isoformat(),
        domains_count=0,
        tenants_count=0,
        mailboxes_count=0,
    )


@router.get("/batches/{batch_id}", response_model=BatchResponse)
async def get_batch(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get a specific batch by ID."""
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    domains_count = (await db.execute(
        select(func.count(Domain.id)).where(Domain.batch_id == batch.id)
    )).scalar() or 0
    
    tenants_count = (await db.execute(
        select(func.count(Tenant.id)).where(Tenant.batch_id == batch.id)
    )).scalar() or 0
    
    mailboxes_count = (await db.execute(
        select(func.count(Mailbox.id)).where(Mailbox.batch_id == batch.id)
    )).scalar() or 0
    
    return BatchResponse(
        id=batch.id,
        name=batch.name,
        description=batch.description,
        current_step=batch.current_step,
        status=batch.status.value,
        redirect_url=batch.redirect_url,
        created_at=batch.created_at.isoformat(),
        domains_count=domains_count,
        tenants_count=tenants_count,
        mailboxes_count=mailboxes_count,
    )


@router.patch("/batches/{batch_id}/pause")
async def pause_batch(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """Pause a batch."""
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    batch.status = BatchStatus.PAUSED
    await db.commit()
    return {"success": True, "message": f"Batch '{batch.name}' paused"}


@router.patch("/batches/{batch_id}/resume")
async def resume_batch(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """Resume a paused batch."""
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    batch.status = BatchStatus.ACTIVE
    await db.commit()
    return {"success": True, "message": f"Batch '{batch.name}' resumed"}


@router.delete("/batches/{batch_id}")
async def delete_batch(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """Delete a batch and optionally its data."""
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    # Note: This only deletes the batch record
    # Domains/tenants/mailboxes remain but become unlinked
    await db.delete(batch)
    await db.commit()
    return {"success": True, "message": f"Batch '{batch.name}' deleted"}


@router.post("/batches/{batch_id}/advance")
async def advance_batch_step(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """Advance batch to the next step."""
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    # Advance to next step (max step is 7 - Complete)
    if batch.current_step < 7:
        batch.current_step = batch.current_step + 1
        await db.commit()
    
    return {"success": True, "current_step": batch.current_step}


# ============== BATCH STATUS ==============

@router.get("/batches/{batch_id}/status", response_model=BatchWizardStatus)
async def get_batch_status(batch_id: UUID, db: RetryableSession = Depends(get_db_session_with_retry)):
    """Get detailed status for a specific batch.
    
    Uses RetryableSession to handle transient connection errors during
    the multiple sequential count queries.
    """
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    # Count domains for this batch
    domains_total = await db.scalar(
        select(func.count(Domain.id)).where(Domain.batch_id == batch_id)
    ) or 0
    
    zones_created = await db.scalar(
        select(func.count(Domain.id)).where(
            Domain.batch_id == batch_id,
            Domain.cloudflare_zone_id.isnot(None)
        )
    ) or 0
    
    ns_propagated = await db.scalar(
        select(func.count(Domain.id)).where(
            Domain.batch_id == batch_id,
            Domain.status == DomainStatus.NS_PROPAGATED
        )
    ) or 0
    
    redirects_configured = await db.scalar(
        select(func.count(Domain.id)).where(
            Domain.batch_id == batch_id,
            Domain.redirect_configured == True
        )
    ) or 0
    
    # Count tenants for this batch
    tenants_total = await db.scalar(
        select(func.count(Tenant.id)).where(Tenant.batch_id == batch_id)
    ) or 0
    
    tenants_linked = await db.scalar(
        select(func.count(Tenant.id)).where(
            Tenant.batch_id == batch_id,
            Tenant.domain_id.isnot(None)
        )
    ) or 0
    
    tenants_m365_verified = await db.scalar(
        select(func.count(Tenant.id)).where(
            Tenant.batch_id == batch_id,
            Tenant.status == TenantStatus.DOMAIN_VERIFIED
        )
    ) or 0
    
    tenants_dkim_enabled = await db.scalar(
        select(func.count(Tenant.id)).where(
            Tenant.batch_id == batch_id,
            Tenant.status == TenantStatus.DKIM_ENABLED
        )
    ) or 0
    
    # Count mailboxes for this batch
    mailboxes_total = await db.scalar(
        select(func.count(Mailbox.id)).where(Mailbox.batch_id == batch_id)
    ) or 0
    
    mailboxes_pending = await db.scalar(
        select(func.count(Mailbox.id)).where(
            Mailbox.batch_id == batch_id,
            Mailbox.status == MailboxStatus.PENDING
        )
    ) or 0
    
    mailboxes_ready = await db.scalar(
        select(func.count(Mailbox.id)).where(
            Mailbox.batch_id == batch_id,
            Mailbox.status == MailboxStatus.READY
        )
    ) or 0
    
    # Determine step name
    step_names = {
        1: "Import Domains",
        2: "Create Zones",
        3: "Verify Nameservers",
        4: "Import Tenants",
        5: "Email Setup",
        6: "Create Mailboxes",
        7: "Complete"
    }
    
    return BatchWizardStatus(
        batch_id=batch.id,
        batch_name=batch.name,
        current_step=batch.current_step,
        step_name=step_names.get(batch.current_step, "Unknown"),
        can_proceed=True,
        status=batch.status.value,
        domains_total=domains_total,
        zones_created=zones_created,
        zones_pending=domains_total - zones_created,
        ns_propagated=ns_propagated,
        ns_pending=zones_created - ns_propagated,
        redirects_configured=redirects_configured,
        tenants_total=tenants_total,
        tenants_linked=tenants_linked,
        tenants_m365_verified=tenants_m365_verified,
        tenants_dkim_enabled=tenants_dkim_enabled,
        mailboxes_total=mailboxes_total,
        mailboxes_pending=mailboxes_pending,
        mailboxes_ready=mailboxes_ready,
    )


# ============== FULL AUTOMATION ENDPOINTS ==============

@router.post("/batches/{batch_id}/start-full-automation")
async def start_full_automation(
    batch_id: UUID,
    new_password: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    mailboxes_per_tenant: int = Form(50),
    max_workers: int = Form(10),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db)
):
    """
    Start complete end-to-end automation.
    
    This will:
    1. Complete first login for all tenants
    2. Get OAuth tokens
    3. Add and verify domains
    4. Configure DNS records
    5. Set up DKIM
    6. Create all mailboxes
    """
    job_id = str(batch_id)
    
    # Initialize tracking
    active_jobs[job_id] = {
        "status": "running",
        "total": 0,
        "completed": 0,
        "started_at": datetime.utcnow().isoformat()
    }
    
    # Count tenants
    result = await db.execute(
        select(Tenant).where(Tenant.batch_id == batch_id)
    )
    tenants = result.scalars().all()
    active_jobs[job_id]["total"] = len(tenants)
    
    config = SetupConfig(
        new_password=new_password,
        first_name=first_name,
        last_name=last_name,
        mailboxes_per_tenant=mailboxes_per_tenant
    )
    
    async def run():
        try:
            def on_progress(completed, total):
                active_jobs[job_id]["completed"] = completed
            
            await process_batch(db, batch_id, config, max_workers, on_progress)
            active_jobs[job_id]["status"] = "completed"
        except Exception as e:
            active_jobs[job_id]["status"] = "error"
            active_jobs[job_id]["error"] = str(e)
    
    background_tasks.add_task(run)
    
    return {
        "success": True,
        "job_id": job_id,
        "message": f"Started automation for {len(tenants)} tenants"
    }


@router.get("/batches/{batch_id}/automation-status")
async def get_automation_status(batch_id: UUID):
    """Get automation progress."""
    job_id = str(batch_id)
    
    if job_id not in active_jobs:
        return {"status": "not_started"}
    
    return active_jobs[job_id]


@router.get("/batches/{batch_id}/export-credentials")
async def export_credentials(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """Export all mailbox credentials as CSV."""
    result = await db.execute(
        select(Mailbox).where(Mailbox.batch_id == batch_id)
    )
    mailboxes = result.scalars().all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Email", "Password", "Display Name"])
    
    for mb in mailboxes:
        writer.writerow([mb.email, mb.password, mb.display_name])
    
    output.seek(0)
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=credentials_{batch_id}.csv"}
    )


# ============== BATCH-SCOPED STEP ENDPOINTS ==============

@router.post("/batches/{batch_id}/step1/import-domains", response_model=StepResult)
async def batch_import_domains(
    batch_id: UUID,
    file: UploadFile = File(...),
    redirect_url: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    """
    Step 1: Import domains for this batch.
    
    CSV can include per-domain redirect URLs:
    - domain,redirect,registrar
    - coldreach.io,https://google.com,porkbun
    
    The redirect_url form field serves as a fallback for domains without a redirect in CSV.
    """
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    # Update batch default redirect URL if provided
    if redirect_url:
        batch.redirect_url = redirect_url
    
    try:
        content = await file.read()
        decoded = content.decode('utf-8')
        
        # Use the new domain import service to parse CSV with per-domain redirects
        parsed_domains = parse_domains_csv(decoded)
        
        created = 0
        skipped = 0
        with_redirect = 0
        
        for domain_data in parsed_domains:
            # Check if domain already exists
            existing = await db.execute(
                select(Domain).where(Domain.name == domain_data.name)
            )
            if existing.scalar_one_or_none():
                skipped += 1
                continue
            
            # Extract TLD
            parts = domain_data.name.split('.')
            tld = parts[-1] if len(parts) > 1 else ''
            
            # Use per-domain redirect from CSV, or fallback to form field / batch default
            domain_redirect = domain_data.redirect_url or redirect_url or batch.redirect_url
            
            if domain_redirect:
                with_redirect += 1
            
            domain = Domain(
                name=domain_data.name,
                tld=tld,
                status=DomainStatus.PURCHASED,
                redirect_url=domain_redirect,
                cloudflare_zone_status='none',
                batch_id=batch_id,  # Link to batch
            )
            db.add(domain)
            created += 1
        
        # Update batch step
        if batch.current_step == 1 and created > 0:
            batch.current_step = 2
        
        await db.commit()
        
        return StepResult(
            success=True,
            message=f"Imported {created} domains ({with_redirect} with redirect), skipped {skipped} duplicates",
            details={
                "created": created, 
                "skipped": skipped,
                "with_redirect": with_redirect,
                "fallback_redirect": redirect_url or batch.redirect_url or None
            }
        )
    
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/batches/{batch_id}/step2/create-zones")
async def batch_create_zones(
    batch_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Step 2: Create/verify Cloudflare zones for all domains in the batch.
    Uses incremental commits to avoid Neon connection timeouts.
    Advances batch to Step 3 on completion.
    """
    # 1. Verify batch exists and is on correct step
    batch_result = await db.execute(
        select(SetupBatch).where(SetupBatch.id == batch_id)
    )
    batch = batch_result.scalar_one_or_none()
    
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    # 2. Get all domain IDs upfront (quick query, then release connection)
    domains_result = await db.execute(
        select(Domain.id, Domain.name, Domain.cloudflare_zone_id, Domain.redirect_url, Domain.redirect_configured)
        .where(Domain.batch_id == batch_id)
    )
    domain_list = domains_result.all()
    
    if not domain_list:
        raise HTTPException(status_code=400, detail="No domains found in batch")
    
    # Get redirect URL from batch
    redirect_url = batch.redirect_url or "https://example.com"
    
    # 3. Process each domain with individual commits (prevents Neon timeout)
    results = []
    success_count = 0
    error_count = 0
    
    for domain_id, domain_name, existing_zone_id, domain_redirect_url, redirect_configured in domain_list:
        try:
            zone_data = None
            nameservers = []
            zone_status = "pending"
            
            # Check if zone already exists in DB
            if existing_zone_id:
                print(f"DEBUG batch_create_zones: {domain_name} has zone_id in DB: {existing_zone_id}")
                # Verify it still exists in Cloudflare
                zone_info = await cloudflare_service.get_zone_by_id(existing_zone_id)
                if zone_info:
                    print(f"DEBUG batch_create_zones: {domain_name} zone verified in CF")
                    zone_data = zone_info
                    nameservers = zone_info.get("nameservers", [])
                    zone_status = zone_info.get("status", "pending")
                else:
                    # Zone was deleted from CF, need to recreate
                    print(f"DEBUG batch_create_zones: {domain_name} zone NOT found in CF, recreating")
                    existing_zone_id = None
            
            # Create zone if needed
            if not existing_zone_id:
                print(f"DEBUG batch_create_zones: Creating zone for {domain_name}")
                zone_result = await cloudflare_service.get_or_create_zone(domain_name)
                if zone_result:
                    zone_data = zone_result
                    existing_zone_id = zone_result.get("zone_id")
                    nameservers = zone_result.get("nameservers", [])
                    zone_status = zone_result.get("status", "pending")
                    print(f"DEBUG batch_create_zones: get_or_create_zone for {domain_name} = {zone_result}")
                else:
                    raise Exception("Failed to create Cloudflare zone")
            
            # Ensure DNS records exist
            if existing_zone_id:
                await cloudflare_service.ensure_email_dns_records(
                    existing_zone_id,
                    domain_name
                )
                print(f"DEBUG batch_create_zones: DNS records verified for {domain_name}")
                
                # Create redirect rule if not already configured
                actual_redirect = domain_redirect_url or redirect_url
                if actual_redirect:
                    await cloudflare_service.create_redirect_rule(
                        existing_zone_id,
                        domain_name,
                        actual_redirect
                    )
                    print(f"DEBUG batch_create_zones: Redirect configured for {domain_name}")
            
            # Determine status based on zone status
            domain_status = "ns_propagated" if zone_status == "active" else "zone_created"
            
            # 4. COMMIT THIS DOMAIN IMMEDIATELY (fresh session to avoid timeout)
            async with async_session_factory() as fresh_db:
                await fresh_db.execute(
                    update(Domain)
                    .where(Domain.id == domain_id)
                    .values(
                        status=domain_status,
                        cloudflare_zone_id=existing_zone_id,
                        cloudflare_nameservers=nameservers,
                        cloudflare_zone_status=zone_status,
                        redirect_configured=True,
                        updated_at=func.now()
                    )
                )
                await fresh_db.commit()
            
            results.append({
                "domain": domain_name,
                "success": True,
                "zone_id": existing_zone_id,
                "status": domain_status,
                "nameservers": nameservers
            })
            success_count += 1
            
        except Exception as e:
            print(f"ERROR batch_create_zones: {domain_name} failed: {str(e)}")
            results.append({
                "domain": domain_name,
                "success": False,
                "error": str(e)
            })
            error_count += 1
    
    # 5. ALL DOMAINS PROCESSED - Now advance the batch to Step 3
    can_progress = error_count == 0
    
    # Always try to advance if we had any success (allow partial progress)
    # Or if all succeeded
    if success_count > 0:
        try:
            async with async_session_factory() as final_db:
                # Update batch to Step 3
                await final_db.execute(
                    update(SetupBatch)
                    .where(SetupBatch.id == batch_id)
                    .values(
                        current_step=3,
                        updated_at=func.now()
                    )
                )
                
                # Also update completed_steps if that column is used
                # Using raw SQL to handle JSONB array append
                await final_db.execute(
                    text("""
                        UPDATE setup_batches 
                        SET completed_steps = COALESCE(completed_steps, '[]'::jsonb) || '2'::jsonb
                        WHERE id = :batch_id 
                        AND NOT (COALESCE(completed_steps, '[]'::jsonb) @> '2'::jsonb)
                    """),
                    {"batch_id": str(batch_id)}
                )
                
                await final_db.commit()
                print(f"DEBUG batch_create_zones: Batch {batch_id} advanced to Step 3")
                
        except Exception as e:
            print(f"ERROR batch_create_zones: Failed to advance batch: {str(e)}")
            # Don't fail the whole request if just the step update fails
            # The domains are already processed
    
    # 6. Return comprehensive response
    return {
        "success": can_progress,
        "message": f"Processed {success_count}/{len(domain_list)} domains successfully",
        "can_progress": can_progress,
        "current_step": 3 if success_count > 0 else 2,
        "summary": {
            "total": len(domain_list),
            "success": success_count,
            "errors": error_count
        },
        "results": results
    }


@router.post("/batches/{batch_id}/step3/check-propagation", response_model=StepResult)
async def batch_check_propagation(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """
    Step 3: Check NS propagation. Auto-advances to Step 4 when ALL domains propagated.
    """
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    # Get all domains with zones (both pending and already propagated)
    result = await db.execute(
        select(Domain).where(
            Domain.batch_id == batch_id,
            Domain.cloudflare_zone_id.isnot(None)
        )
    )
    domains = result.scalars().all()
    
    propagated = 0
    pending = 0
    
    for domain in domains:
        # Skip already propagated domains
        if domain.status == DomainStatus.NS_PROPAGATED:
            propagated += 1
            continue
        
        if domain.cloudflare_nameservers:
            try:
                is_propagated = await cloudflare_service.check_ns_propagation(
                    domain.name, domain.cloudflare_nameservers
                )
                
                if is_propagated:
                    domain.status = DomainStatus.NS_PROPAGATED
                    domain.ns_propagated_at = datetime.utcnow()
                    propagated += 1
                else:
                    pending += 1
            except Exception as e:
                pending += 1
                print(f"NS check error for {domain.name}: {e}")
    
    await db.commit()
    
    # Auto-advance to Step 4 ONLY if ALL domains propagated
    all_propagated = pending == 0 and propagated > 0
    auto_advanced = False
    
    if all_propagated and batch.current_step == 3:
        batch.current_step = 4
        auto_advanced = True
        await db.commit()
    
    return StepResult(
        success=True,
        message=f"{propagated} propagated, {pending} pending",
        details={
            "propagated": propagated,
            "pending": pending,
            "all_propagated": all_propagated,
            "auto_advanced": auto_advanced
        }
    )


@router.post("/batches/{batch_id}/step3/retry-redirects", response_model=StepResult)
async def batch_retry_redirects(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """Retry failed redirects (for domains where redirect_configured is False)."""
    import asyncio
    
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    result = await db.execute(
        select(Domain).where(
            Domain.batch_id == batch_id,
            Domain.cloudflare_zone_id.isnot(None),
            Domain.redirect_configured == False
        )
    )
    domains = result.scalars().all()
    
    success = 0
    failed = 0
    
    for domain in domains:
        redirect_url = domain.redirect_url or batch.redirect_url
        if not redirect_url:
            continue
            
        try:
            await asyncio.sleep(0.25)
            res = await cloudflare_service.create_redirect_rule(
                domain.cloudflare_zone_id, domain.name, redirect_url
            )
            if res.get('success'):
                domain.redirect_configured = True
                success += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            print(f"Redirect retry error for {domain.name}: {e}")
    
    await db.commit()
    
    return StepResult(
        success=True,
        message=f"Retried redirects: {success} success, {failed} failed",
        details={"success": success, "failed": failed}
    )


@router.post("/batches/{batch_id}/step3/continue-anyway", response_model=StepResult)
async def batch_continue_anyway(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """Force advance to Step 4 even if NS not fully propagated."""
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    if batch.current_step == 3:
        batch.current_step = 4
        await db.commit()
    
    return StepResult(
        success=True,
        message="Advanced to Step 4. Note: Some features require NS propagation.",
        details={"new_step": 4}
    )


@router.get("/batches/{batch_id}/nameserver-groups")
async def batch_get_nameserver_groups(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """
    Get nameserver groups for a batch.
    Returns domains grouped by their Cloudflare nameservers.
    """
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    # Get all domains with zones in this batch
    result = await db.execute(
        select(Domain).where(
            Domain.batch_id == batch_id,
            Domain.cloudflare_zone_id.isnot(None)
        )
    )
    domains = result.scalars().all()
    
    # Group by nameservers
    ns_groups: dict = {}
    
    for domain in domains:
        nameservers = domain.cloudflare_nameservers or []
        if nameservers:
            ns_key = tuple(sorted(nameservers))
        else:
            ns_key = ("nameservers-pending",)
        
        if ns_key not in ns_groups:
            ns_groups[ns_key] = {
                "propagated": [],
                "pending": []
            }
        
        # Check if propagated
        if domain.status == DomainStatus.NS_PROPAGATED:
            ns_groups[ns_key]["propagated"].append(domain.name)
        else:
            ns_groups[ns_key]["pending"].append(domain.name)
    
    # Format response
    nameserver_groups = [
        {
            "nameservers": list(ns),
            "domain_count": len(data["propagated"]) + len(data["pending"]),
            "domains": data["propagated"] + data["pending"],
            "propagated_count": len(data["propagated"]),
            "pending_count": len(data["pending"])
        }
        for ns, data in ns_groups.items()
    ]
    
    return {
        "success": True,
        "nameserver_groups": nameserver_groups
    }


# Legacy endpoint for backward compatibility - now just retries redirects
@router.post("/batches/{batch_id}/step3/setup-redirects", response_model=StepResult)
async def batch_setup_redirects(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """Step 3b: Setup/retry redirects for this batch (legacy endpoint)."""
    # Redirect to the new retry-redirects endpoint logic
    return await batch_retry_redirects(batch_id, db)


# ============== STEP 4 ENDPOINTS ==============

@router.post("/batches/{batch_id}/step4/import-tenants")
async def import_tenants(
    batch_id: UUID,
    tenant_csv: UploadFile = File(...),
    credentials_txt: UploadFile = File(...),
    provider: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """Import tenants from reseller files."""
    csv_content = (await tenant_csv.read()).decode('utf-8-sig')
    txt_content = (await credentials_txt.read()).decode('utf-8-sig')
    
    result = await tenant_import_service.import_tenants(
        db, batch_id, csv_content, txt_content, provider
    )
    
    return {"success": True, "details": result}


@router.post("/batches/{batch_id}/step4/link-domains")
async def link_domains(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """Auto-link tenants to domains."""
    result = await tenant_import_service.auto_link_domains(db, batch_id)
    return {"success": True, "details": result}


@router.post("/batches/{batch_id}/step4/start-automation")
async def start_automation(
    batch_id: UUID,
    new_password: str = Form(...),
    max_workers: int = Form(default=10),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db)
):
    """Start parallel first-login automation."""
    import logging
    logger = logging.getLogger(__name__)

    # STEP 4 FIX: Enforce max 2 concurrent workers to avoid browser rendering issues
    STEP4_MAX_WORKERS = 2
    if max_workers > STEP4_MAX_WORKERS:
        logger.warning(
            "Step 4 max_workers capped at %s (requested %s)",
            STEP4_MAX_WORKERS,
            max_workers,
        )
        max_workers = STEP4_MAX_WORKERS
    
    # Check if automation is already running for this batch
    job_id = str(batch_id)
    if job_id in step4_jobs and step4_jobs[job_id].get("status") == "running":
        logger.warning(f"Step 4 automation already running for batch {batch_id}")
        return {
            "success": False,
            "message": f"Automation already running for this batch (started at {step4_jobs[job_id].get('started_at')})",
            "already_running": True
        }
    
    # STEP 4 FIX: Exclude tenants that already have TOTP saved to prevent re-enrollment
    tenants = (await db.execute(
        select(Tenant).where(
            Tenant.batch_id == batch_id,
            Tenant.first_login_completed == False,
            Tenant.totp_secret.is_(None)  # Skip already-completed tenants
        )
    )).scalars().all()
    
    if not tenants:
        return {"success": True, "message": "No tenants"}
    
    # CRITICAL LOGGING: Log the actual max_workers value being used
    logger.info(f"=" * 60)
    logger.info(f"STEP 4 AUTOMATION STARTING")
    logger.info(f"Batch ID: {batch_id}")
    logger.info(f"Max Workers (parallel browsers): {max_workers}")
    logger.info(f"Total tenants: {len(tenants)}")
    logger.info(f"=" * 60)
    
    tenant_data = [
        {"tenant_id": str(t.id), "admin_email": t.admin_email, "initial_password": t.admin_password}
        for t in tenants
    ]
    
    # Initialize job tracking
    step4_jobs[job_id] = {
        "status": "running",
        "total": len(tenants),
        "max_workers": max_workers,
        "started_at": datetime.utcnow().isoformat()
    }
    
    async def run():
        try:
            results = await process_tenants_parallel(tenant_data, new_password, max_workers)
            for r in results:
                async with AsyncSession(async_engine, expire_on_commit=False) as session:
                    t = await session.get(Tenant, UUID(r["tenant_id"]))
                    if t:
                        t.first_login_completed = r["success"]
                        t.totp_secret = r["totp_secret"]
                        t.security_defaults_disabled = r["security_defaults_disabled"]
                        t.setup_error = r["error"]
                        if r["success"]:
                            # Only update admin_password AFTER successful password change
                            # This preserves the original TXT password until change is confirmed
                            if r["new_password"]:  # Only update if we have a new password
                                t.admin_password = r["new_password"]
                                t.password_changed = True  # CRITICAL: Mark password as changed!
                            t.first_login_at = datetime.utcnow()
                        await session.commit()
                        logger.info(" SAVED %s to DB", t.name)
            
            # Mark job as completed
            step4_jobs[job_id]["status"] = "completed"
            step4_jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()
            logger.info(f"Step 4 automation completed for batch {batch_id}")
            
        except Exception as e:
            # Mark job as failed
            step4_jobs[job_id]["status"] = "failed"
            step4_jobs[job_id]["error"] = str(e)
            step4_jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()
            logger.error(f"Step 4 automation failed for batch {batch_id}: {str(e)}")
    
    background_tasks.add_task(run)
    
    return {
        "success": True,
        "tenants": len(tenants),
        "workers": max_workers,
        "estimated_minutes": round(len(tenants) / max_workers * 1.5)
    }


@router.get("/batches/{batch_id}/step4/progress")
async def get_automation_progress(batch_id: UUID):
    """Get automation progress."""
    return get_progress()


@router.get("/batches/{batch_id}/step4/status")
async def get_step4_status(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get step 4 completion status."""
    tenants = (await db.execute(
        select(Tenant).where(Tenant.batch_id == batch_id)
    )).scalars().all()
    
    domains = (await db.execute(
        select(Domain).where(Domain.batch_id == batch_id)
    )).scalars().all()
    
    # Count failed tenants (have error but not completed)
    failed_count = sum(1 for t in tenants if t.setup_error and not t.first_login_completed)
    
    return {
        "tenants_total": len(tenants),
        "tenants_first_login_complete": sum(1 for t in tenants if t.first_login_completed),
        "tenants_linked": sum(1 for t in tenants if t.domain_id),
        "tenants_failed": failed_count,
        "domains_total": len(domains),
        "ready_for_step5": all(t.first_login_completed and t.domain_id for t in tenants)
    }


@router.post("/batches/{batch_id}/step4/skip-tenant/{tenant_id}")
async def skip_tenant_first_login(
    batch_id: UUID,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Skip first login for a failed tenant so user can proceed."""
    tenant = await db.get(Tenant, tenant_id)
    
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    if tenant.batch_id != batch_id:
        raise HTTPException(status_code=400, detail="Tenant does not belong to this batch")
    
    # Mark as completed (skipped) so it doesn't block progress
    tenant.first_login_completed = True
    if not tenant.setup_error:
        tenant.setup_error = "SKIPPED: Skipped by user"
    else:
        tenant.setup_error = f"SKIPPED: {tenant.setup_error}"
    
    await db.commit()
    
    return {"success": True, "message": f"Skipped tenant {tenant.name}"}


@router.post("/batches/{batch_id}/step4/retry-tenant/{tenant_id}")
async def retry_tenant_first_login(
    batch_id: UUID,
    tenant_id: UUID,
    new_password: str = Form(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db)
):
    """Retry first login for a single tenant."""
    tenant = await db.get(Tenant, tenant_id)
    
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    if tenant.batch_id != batch_id:
        raise HTTPException(status_code=400, detail="Tenant does not belong to this batch")
    
    # Clear error and retry
    tenant.setup_error = None
    tenant.first_login_completed = False
    await db.commit()
    
    # Queue retry in background
    tenant_data = [{
        "tenant_id": str(tenant.id),
        "admin_email": tenant.admin_email,
        "initial_password": tenant.admin_password
    }]
    
    async def run_retry():
        results = await process_tenants_parallel(tenant_data, new_password, max_workers=1)
        for r in results:
            async with AsyncSession(async_engine, expire_on_commit=False) as session:
                t = await session.get(Tenant, UUID(r["tenant_id"]))
                if t:
                    t.first_login_completed = r["success"]
                    t.totp_secret = r["totp_secret"]
                    t.security_defaults_disabled = r["security_defaults_disabled"]
                    t.setup_error = r["error"]
                    if r["success"] and r["new_password"]:
                        t.admin_password = r["new_password"]
                        t.password_changed = True
                        t.first_login_at = datetime.utcnow()
                    await session.commit()
                    logger.info(" SAVED %s to DB", t.name)
    
    background_tasks.add_task(run_retry)
    
    return {"success": True, "message": f"Retrying tenant {tenant.name}"}


@router.post("/batches/{batch_id}/step4/skip-all-failed")
async def skip_all_failed_tenants(
    batch_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Skip all failed tenants in a batch."""
    result = await db.execute(
        select(Tenant).where(
            Tenant.batch_id == batch_id,
            Tenant.first_login_completed == False,
            Tenant.setup_error.isnot(None)
        )
    )
    failed_tenants = result.scalars().all()
    
    skipped_count = 0
    for tenant in failed_tenants:
        tenant.first_login_completed = True
        tenant.setup_error = f"SKIPPED: {tenant.setup_error}"
        skipped_count += 1
    
    await db.commit()
    
    return {
        "success": True, 
        "skipped_count": skipped_count,
        "message": f"Skipped {skipped_count} failed tenant(s)"
    }


# ============== STEP 5 ENDPOINTS ==============

@router.get("/batches/{batch_id}/step5/script/add-domain/{tenant_id}")
async def get_add_domain_script(batch_id: UUID, tenant_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get script to add domain to M365."""
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    script = m365_scripts.generate_add_domain_script(
        tenant.microsoft_tenant_id, tenant.custom_domain
    )
    return PlainTextResponse(script, media_type="text/plain")


@router.post("/batches/{batch_id}/step5/save-verification-txt/{tenant_id}")
async def save_verification_txt(
    batch_id: UUID,
    tenant_id: UUID,
    txt_value: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """Save MS verification TXT and add to Cloudflare."""
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.m365_verification_txt = txt_value
    
    # Add to Cloudflare
    domain = await db.get(Domain, tenant.domain_id)
    if domain and domain.cloudflare_zone_id:
        await cloudflare_service.create_txt_record(
            domain.cloudflare_zone_id,
            "@",
            txt_value
        )
    
    tenant.domain_added_to_m365 = True
    await db.commit()
    
    return {"success": True}


@router.get("/batches/{batch_id}/step5/script/verify-domain/{tenant_id}")
async def get_verify_domain_script(batch_id: UUID, tenant_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get script to verify domain."""
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    script = m365_scripts.generate_verify_domain_script(
        tenant.microsoft_tenant_id, tenant.custom_domain
    )
    return PlainTextResponse(script, media_type="text/plain")


@router.post("/batches/{batch_id}/step5/mark-verified/{tenant_id}")
async def mark_domain_verified(batch_id: UUID, tenant_id: UUID, db: AsyncSession = Depends(get_db)):
    """Mark domain as verified."""
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.domain_verified_in_m365 = True
    tenant.domain_verified_at = datetime.utcnow()
    await db.commit()
    return {"success": True}


@router.post("/batches/{batch_id}/step5/add-mail-dns/{tenant_id}")
async def add_mail_dns(batch_id: UUID, tenant_id: UUID, db: AsyncSession = Depends(get_db)):
    """Add MX, SPF, Autodiscover records."""
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    domain = await db.get(Domain, tenant.domain_id)
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    
    dns = m365_scripts.get_mail_dns_values(tenant.custom_domain)
    
    # Add MX
    await cloudflare_service.create_mx_record(
        domain.cloudflare_zone_id, dns["mx"]["name"], dns["mx"]["target"], dns["mx"]["priority"]
    )
    tenant.mx_record_added = True
    
    # Add SPF
    await cloudflare_service.create_txt_record(
        domain.cloudflare_zone_id, dns["spf"]["name"], dns["spf"]["value"]
    )
    tenant.spf_record_added = True
    
    # Add Autodiscover
    await cloudflare_service.create_cname_record(
        domain.cloudflare_zone_id, dns["autodiscover"]["name"], dns["autodiscover"]["target"], proxied=False
    )
    tenant.autodiscover_added = True
    
    await db.commit()
    return {"success": True}


@router.get("/batches/{batch_id}/step5/script/get-dkim/{tenant_id}")
async def get_dkim_script(batch_id: UUID, tenant_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get script to retrieve DKIM values."""
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    script = m365_scripts.generate_get_dkim_script(
        tenant.microsoft_tenant_id, tenant.custom_domain
    )
    return PlainTextResponse(script, media_type="text/plain")


@router.post("/batches/{batch_id}/step5/save-dkim/{tenant_id}")
async def save_dkim_values(
    batch_id: UUID,
    tenant_id: UUID,
    selector1: str = Form(...),
    selector2: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """Save DKIM values and add CNAMEs to Cloudflare."""
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    domain = await db.get(Domain, tenant.domain_id)
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    
    tenant.dkim_selector1 = selector1
    tenant.dkim_selector2 = selector2
    
    # Add DKIM CNAMEs (MUST be proxied=False!)
    await cloudflare_service.create_cname_record(
        domain.cloudflare_zone_id, "selector1._domainkey", selector1, proxied=False
    )
    await cloudflare_service.create_cname_record(
        domain.cloudflare_zone_id, "selector2._domainkey", selector2, proxied=False
    )
    
    tenant.dkim_cnames_added = True
    await db.commit()
    
    return {"success": True}


@router.get("/batches/{batch_id}/step5/script/enable-dkim/{tenant_id}")
async def get_enable_dkim_script(batch_id: UUID, tenant_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get script to enable DKIM."""
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    script = m365_scripts.generate_enable_dkim_script(
        tenant.microsoft_tenant_id, tenant.custom_domain
    )
    return PlainTextResponse(script, media_type="text/plain")


@router.post("/batches/{batch_id}/step5/mark-dkim-enabled/{tenant_id}")
async def mark_dkim_enabled(batch_id: UUID, tenant_id: UUID, db: AsyncSession = Depends(get_db)):
    """Mark DKIM as enabled."""
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.dkim_enabled = True
    tenant.dkim_enabled_at = datetime.utcnow()
    await db.commit()
    return {"success": True}


@router.post("/batches/{batch_id}/step5/setup-m365", response_model=StepResult)
async def batch_setup_m365(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """Step 5a: Setup M365 for this batch (legacy placeholder)."""
    return StepResult(
        success=True,
        message="Use the per-tenant endpoints for M365 setup",
        details={"note": "See /step5/script/* and /step5/save-* endpoints"}
    )


@router.post("/batches/{batch_id}/step5/setup-dkim", response_model=StepResult)
async def batch_setup_dkim(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """Step 5b: Setup DKIM for this batch (legacy placeholder)."""
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    if batch.current_step == 5:
        batch.current_step = 6
        await db.commit()
    
    return StepResult(
        success=True,
        message="Use the per-tenant endpoints for DKIM setup",
        details={"note": "See /step5/script/get-dkim/* and /step5/save-dkim/* endpoints"}
    )


# ============== STEP 5 AUTOMATION ENDPOINTS ==============

# Store Step 5 job progress
step5_jobs = {}


@router.post("/batches/{batch_id}/step5/start-automation")
async def start_step5_automation(
    batch_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Start automated M365 domain verification and DKIM setup for all tenants in batch.
    
    This runs in the background and:
    1. Adds domain to M365 tenant (via Graph API)
    2. Adds verification TXT to Cloudflare
    3. Waits for DNS propagation
    4. Verifies domain in M365
    5. Adds mail DNS records (MX, SPF, autodiscover)
    6. Gets DKIM CNAME values (via Exchange Online PowerShell)
    7. Adds DKIM CNAMEs to Cloudflare
    8. Waits for propagation
    9. Enables DKIM
    
    Requires:
    - Tenants must have completed first login (Step 4)
    - Tenants must have OAuth tokens stored
    - Tenants must be linked to domains
    """
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    # Count eligible tenants
    result = await db.execute(
        select(Tenant).where(
            Tenant.batch_id == batch_id,
            Tenant.domain_id.isnot(None),
            Tenant.first_login_completed == True,
            Tenant.dkim_enabled != True
        )
    )
    tenants = result.scalars().all()
    
    if not tenants:
        return {
            "success": False,
            "message": "No eligible tenants found. Ensure tenants have completed first login and are linked to domains."
        }
    
    job_id = str(batch_id)
    
    # Initialize job tracking
    step5_jobs[job_id] = {
        "status": "running",
        "total": len(tenants),
        "completed": 0,
        "successful": 0,
        "failed": 0,
        "current_tenant": None,
        "current_step": None,
        "started_at": datetime.utcnow().isoformat(),
        "results": []
    }
    
    async def run_automation():
        try:
            # Create fresh DB session for background task
            from app.db.session import async_engine
            async with AsyncSession(async_engine, expire_on_commit=False) as bg_db:
                def on_progress(tenant_id: str, step: str, status: str):
                    step5_jobs[job_id]["current_tenant"] = tenant_id
                    step5_jobs[job_id]["current_step"] = f"{step}: {status}"
                
                summary = await run_step5_for_batch(batch_id, on_progress)
                
                step5_jobs[job_id]["status"] = "completed"
                step5_jobs[job_id]["completed"] = summary["total"]
                step5_jobs[job_id]["successful"] = summary["successful"]
                step5_jobs[job_id]["failed"] = summary["failed"]
                step5_jobs[job_id]["results"] = summary["results"]
                step5_jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()
                
        except Exception as e:
            step5_jobs[job_id]["status"] = "error"
            step5_jobs[job_id]["error"] = str(e)
    
    background_tasks.add_task(run_automation)
    
    return {
        "success": True,
        "job_id": job_id,
        "message": f"Started Step 5 automation for {len(tenants)} tenants",
        "total_tenants": len(tenants),
        "estimated_minutes": len(tenants) * 5  # ~5 min per tenant
    }


@router.get("/batches/{batch_id}/step5/automation-status")
async def get_step5_automation_status(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get the current status of Step 5 automation with real-time live progress.
    
    This endpoint combines:
    1. Job-level status (from step5_jobs in-memory dict)
    2. Real-time per-domain progress (from status files written by automation)
    
    The live progress shows exactly what step each domain is on during automation.
    """
    job_id = str(batch_id)
    
    # Get live progress from status files (written by admin_portal automation)
    live_progress = get_live_progress()
    
    # Get tenants for this batch to map domains
    result = await db.execute(
        select(Tenant).where(Tenant.batch_id == batch_id)
    )
    tenants = result.scalars().all()
    
    # Build per-domain live status
    tenant_live_status = []
    active_count = 0
    
    for tenant in tenants:
        domain = tenant.custom_domain
        if domain:
            progress = live_progress.get(domain, {})
            is_active = bool(progress) and progress.get("status") == "in_progress"
            if is_active:
                active_count += 1
            
            tenant_live_status.append({
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
                "domain": domain,
                "live_step": progress.get("step", ""),
                "live_status": progress.get("status", ""),
                "live_details": progress.get("details", ""),
                "active": is_active,
                "timestamp": progress.get("timestamp")
            })
    
    if job_id not in step5_jobs:
        # Return a proper structure even when no job exists
        # Include live progress for domains that may be processing
        return {
            "status": "not_started" if active_count == 0 else "running",
            "message": "No automation job found for this batch" if active_count == 0 else f"{active_count} domain(s) processing",
            "total": 0,
            "completed": 0,
            "successful": 0,
            "failed": 0,
            "current_tenant": None,
            "current_step": None,
            "error": None,
            "active_domains": active_count,
            "tenant_live_progress": tenant_live_status
        }
    
    # Return job status with all expected fields (fill in defaults for missing)
    job = step5_jobs[job_id]
    return {
        "status": job.get("status", "unknown"),
        "message": job.get("message"),
        "total": job.get("total", 0),
        "completed": job.get("completed", 0),
        "successful": job.get("successful", 0),
        "failed": job.get("failed", 0),
        "current_tenant": job.get("current_tenant"),
        "current_step": job.get("current_step"),
        "error": job.get("error"),
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "results": job.get("results", []),
        "active_domains": active_count,
        "tenant_live_progress": tenant_live_status
    }


@router.post("/batches/{batch_id}/step5/setup-tenant/{tenant_id}")
async def setup_single_tenant(
    batch_id: UUID,
    tenant_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Start Step 5 automation for a single tenant.
    
    Useful for:
    - Retrying failed tenants
    - Testing with one tenant before running batch
    """
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    if tenant.batch_id != batch_id:
        raise HTTPException(status_code=400, detail="Tenant does not belong to this batch")
    
    if not tenant.domain_id:
        raise HTTPException(status_code=400, detail="Tenant has no linked domain")
    
    if not tenant.first_login_completed:
        raise HTTPException(status_code=400, detail="Tenant has not completed first login")
    
    domain = await db.get(Domain, tenant.domain_id)
    if not domain:
        raise HTTPException(status_code=404, detail="Linked domain not found")
    
    job_id = f"{batch_id}_{tenant_id}"
    
    step5_jobs[job_id] = {
        "status": "running",
        "tenant_id": str(tenant_id),
        "domain": domain.name,
        "current_step": "starting",
        "started_at": datetime.utcnow().isoformat()
    }
    
    async def run_single():
        try:
            from app.db.session import async_engine
            async with AsyncSession(async_engine, expire_on_commit=False) as bg_db:
                def on_progress(step: str, status: str):
                    step5_jobs[job_id]["current_step"] = f"{step}: {status}"
                
                result = await run_step5_for_tenant(bg_db, tenant_id, on_progress)
                
                step5_jobs[job_id]["status"] = "completed" if result.success else "failed"
                step5_jobs[job_id]["result"] = result.to_dict()
                step5_jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()
                
        except Exception as e:
            step5_jobs[job_id]["status"] = "error"
            step5_jobs[job_id]["error"] = str(e)
    
    background_tasks.add_task(run_single)
    
    return {
        "success": True,
        "job_id": job_id,
        "message": f"Started Step 5 for tenant {tenant.name} / {domain.name}"
    }


@router.get("/batches/{batch_id}/step5/tenant-status/{tenant_id}")
async def get_tenant_setup_status(
    batch_id: UUID,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get Step 5 status for a specific tenant."""
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    domain = None
    if tenant.domain_id:
        domain = await db.get(Domain, tenant.domain_id)
    
    return {
        "tenant_id": str(tenant.id),
        "tenant_name": tenant.name,
        "domain": domain.name if domain else None,
        "status": tenant.status.value,
        "steps": {
            "has_oauth_token": bool(tenant.access_token),
            "domain_added_to_m365": tenant.domain_added_to_m365,
            "verification_txt": tenant.m365_verification_txt,
            "domain_verified": tenant.domain_verified_in_m365,
            "domain_verified_at": tenant.domain_verified_at.isoformat() if tenant.domain_verified_at else None,
            "mx_added": tenant.mx_record_added,
            "spf_added": tenant.spf_record_added,
            "autodiscover_added": tenant.autodiscover_added,
            "dkim_selector1": tenant.dkim_selector1_cname,
            "dkim_selector2": tenant.dkim_selector2_cname,
            "dkim_cnames_added": tenant.dkim_cnames_added,
            "dkim_enabled": tenant.dkim_enabled,
            "dkim_enabled_at": tenant.dkim_enabled_at.isoformat() if tenant.dkim_enabled_at else None
        },
        "error": tenant.setup_error
    }


@router.get("/batches/{batch_id}/step5/status")
async def get_step5_batch_status(
    batch_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get Step 5 status for all tenants in batch."""
    result = await db.execute(
        select(Tenant).where(Tenant.batch_id == batch_id)
    )
    tenants = result.scalars().all()
    
    summary = {
        "total": len(tenants),
        "not_started": 0,
        "domain_added": 0,
        "domain_verified": 0,
        "dns_configured": 0,
        "dkim_cnames_added": 0,
        "dkim_enabled": 0,
        "errored": 0,
        "tenants": []
    }
    
    for tenant in tenants:
        tenant_status = {
            "id": str(tenant.id),
            "name": tenant.name,
            "domain": tenant.custom_domain,
            "status": tenant.status.value,
            "domain_added": tenant.domain_added_to_m365,
            "domain_verified": tenant.domain_verified_in_m365,
            "dns_configured": tenant.mx_record_added and tenant.spf_record_added,
            "dkim_cnames_added": tenant.dkim_cnames_added,
            "dkim_enabled": tenant.dkim_enabled,
            "error": tenant.setup_error
        }
        summary["tenants"].append(tenant_status)
        
        # Count statuses
        if tenant.setup_error:
            summary["errored"] += 1
        elif tenant.dkim_enabled:
            summary["dkim_enabled"] += 1
        elif tenant.dkim_cnames_added:
            summary["dkim_cnames_added"] += 1
        elif tenant.mx_record_added:
            summary["dns_configured"] += 1
        elif tenant.domain_verified_in_m365:
            summary["domain_verified"] += 1
        elif tenant.domain_added_to_m365:
            summary["domain_added"] += 1
        else:
            summary["not_started"] += 1
    
    # Determine if ready to advance to Step 6
    summary["ready_for_step6"] = summary["dkim_enabled"] == summary["total"] and summary["total"] > 0
    
    return summary


@router.post("/batches/{batch_id}/step5/retry-dkim")
async def retry_dkim_for_batch(
    batch_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Manually trigger DKIM enable retry for tenants in this batch.
    
    This runs the background DKIM retry job immediately for this batch's tenants.
    Useful when you don't want to wait for the scheduled 10-minute interval.
    """
    from app.services.background_jobs import trigger_dkim_retry_now, get_dkim_retry_status
    
    # Get status first
    status = await get_dkim_retry_status()
    
    # Filter to just this batch's tenants
    batch_tenants = [t for t in status.get("tenants", []) if True]  # All pending tenants for now
    
    # Trigger the retry job
    background_tasks.add_task(trigger_dkim_retry_now)
    
    return {
        "success": True,
        "message": "DKIM retry job triggered",
        "pending_count": status.get("pending_count", 0),
        "retry_interval_minutes": status.get("retry_interval_minutes", 10),
        "retry_window_hours": status.get("retry_window_hours", 24)
    }


@router.get("/batches/{batch_id}/step5/dkim-retry-status")
async def get_batch_dkim_retry_status(
    batch_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Get status of pending DKIM retries for tenants in this batch.
    
    Shows which tenants are waiting for DKIM enable and their retry history.
    """
    from app.services.background_jobs import get_dkim_retry_status
    
    # Get all pending DKIM retries
    status = await get_dkim_retry_status()
    
    # Get batch tenants to filter
    result = await db.execute(
        select(Tenant).where(Tenant.batch_id == batch_id)
    )
    batch_tenant_ids = {str(t.id) for t in result.scalars().all()}
    
    # Filter to just this batch
    batch_tenants = [
        t for t in status.get("tenants", [])
        if t.get("tenant_id") in batch_tenant_ids
    ]
    
    return {
        "batch_id": str(batch_id),
        "pending_count": len(batch_tenants),
        "retry_interval_minutes": status.get("retry_interval_minutes", 10),
        "retry_window_hours": status.get("retry_window_hours", 24),
        "tenants": batch_tenants
    }


@router.post("/batches/{batch_id}/step5/retry-dkim/{tenant_id}")
async def retry_dkim_for_tenant(
    batch_id: UUID,
    tenant_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Manually trigger DKIM enable retry for a single tenant.
    
    Immediately attempts to enable DKIM via Exchange Admin Center UI.
    """
    from app.services.selenium.admin_portal import AdminPortalAutomation
    from datetime import datetime
    
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    if tenant.batch_id != batch_id:
        raise HTTPException(status_code=400, detail="Tenant does not belong to this batch")
    
    if not tenant.domain_id:
        raise HTTPException(status_code=400, detail="Tenant has no linked domain")
    
    if not tenant.dkim_cnames_added:
        raise HTTPException(status_code=400, detail="DKIM CNAMEs not yet added")
    
    if tenant.dkim_enabled:
        return {"success": True, "message": "DKIM already enabled", "already_enabled": True}
    
    domain = await db.get(Domain, tenant.domain_id)
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    
    # Update retry tracking
    tenant.dkim_retry_count += 1
    tenant.dkim_last_retry_at = datetime.utcnow()
    await db.commit()
    
    # Run in background
    async def do_retry():
        try:
            automation = AdminPortalAutomation(headless=True)
            result = await automation.enable_dkim_via_ui(
                admin_email=tenant.admin_email,
                admin_password=tenant.admin_password,
                totp_secret=tenant.totp_secret,
                domain_name=domain.name
            )
            
            async with AsyncSession(async_engine, expire_on_commit=False) as session:
                t = await session.get(Tenant, tenant_id)
                d = await session.get(Domain, domain.id)
                
                if result.success:
                    t.dkim_enabled = True
                    t.dkim_enabled_at = datetime.utcnow()
                    t.status = TenantStatus.DKIM_ENABLED
                    t.setup_error = None
                    d.dkim_enabled = True
                    d.status = "active"
                
                await session.commit()
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"DKIM retry error for {domain.name}: {e}")
    
    background_tasks.add_task(do_retry)
    
    return {
        "success": True,
        "message": f"DKIM retry triggered for {domain.name}",
        "retry_count": tenant.dkim_retry_count,
        "tenant_id": str(tenant_id)
    }


@router.post("/batches/{batch_id}/step5/start-parallel")
async def start_step5_parallel(
    batch_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Start PARALLEL M365 domain verification for all tenants in batch.
    
    This uses the parallel processor which:
    - Runs up to 3 browsers simultaneously
    - Handles DNS propagation waits intelligently
    - While one domain waits for DNS, starts processing others
    - Retries verification every 2 minutes (max 10 attempts = 20 min)
    
    Much faster than sequential processing for batches with many domains.
    """
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    # Get eligible tenants with their domains
    result = await db.execute(
        select(Tenant).where(
            Tenant.batch_id == batch_id,
            Tenant.domain_id.isnot(None),
            Tenant.first_login_completed == True,
            Tenant.dkim_enabled != True
        )
    )
    tenants = result.scalars().all()
    
    if not tenants:
        return {
            "success": False,
            "message": "No eligible tenants found. Ensure tenants have completed first login and are linked to domains."
        }
    
    # Build tenant data for parallel processor
    tenants_data = []
    for tenant in tenants:
        domain = await db.get(Domain, tenant.domain_id)
        if not domain or not domain.cloudflare_zone_id:
            continue
        
        tenants_data.append({
            "tenant_id": tenant.id,
            "domain_id": domain.id,
            "domain_name": domain.name,
            "admin_email": tenant.admin_email,
            "admin_password": tenant.admin_password,
            "totp_secret": tenant.totp_secret,
            "cloudflare_zone_id": domain.cloudflare_zone_id
        })
    
    if not tenants_data:
        return {
            "success": False,
            "message": "No tenants with valid Cloudflare zones found."
        }
    
    job_id = f"{batch_id}_parallel"
    
    # Initialize job tracking
    step5_jobs[job_id] = {
        "status": "running",
        "mode": "parallel",
        "max_browsers": 3,
        "total": len(tenants_data),
        "completed": 0,
        "successful": 0,
        "failed": 0,
        "waiting_dns": 0,
        "current_domains": [],
        "started_at": datetime.utcnow().isoformat(),
        "results": []
    }
    
    async def run_parallel():
        try:
            def on_progress(domain_name: str, state: str, message: str):
                step5_jobs[job_id]["current_step"] = f"{domain_name}: {state} - {message}"
                # Track active domains
                if state == "starting":
                    if domain_name not in step5_jobs[job_id]["current_domains"]:
                        step5_jobs[job_id]["current_domains"].append(domain_name)
                elif state == "waiting":
                    step5_jobs[job_id]["waiting_dns"] = len([
                        d for d in step5_jobs[job_id]["current_domains"]
                    ])
            
            def on_complete(domain_name: str, success: bool, result: dict):
                step5_jobs[job_id]["completed"] += 1
                if success:
                    step5_jobs[job_id]["successful"] += 1
                else:
                    step5_jobs[job_id]["failed"] += 1
                step5_jobs[job_id]["results"].append(result)
                # Remove from active
                if domain_name in step5_jobs[job_id]["current_domains"]:
                    step5_jobs[job_id]["current_domains"].remove(domain_name)
            
            summary = await run_parallel_step5(
                tenants_data,
                on_progress=on_progress,
                on_complete=on_complete
            )
            
            step5_jobs[job_id]["status"] = "completed"
            step5_jobs[job_id]["successful"] = summary["successful"]
            step5_jobs[job_id]["failed"] = summary["failed"]
            step5_jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()
            
            # Update database with results
            from app.db.session import async_engine
            async with AsyncSession(async_engine, expire_on_commit=False) as bg_db:
                for result in summary["results"]:
                    if result.get("success"):
                        tenant = await bg_db.execute(
                            select(Tenant).where(Tenant.id == UUID(result["tenant_id"]))
                        )
                        tenant = tenant.scalar_one_or_none()
                        if tenant:
                            tenant.domain_verified_in_m365 = result.get("domain_verified", False)
                            tenant.dkim_enabled = result.get("dkim_enabled", False)
                            if result.get("dkim_enabled"):
                                tenant.dkim_enabled_at = datetime.utcnow()
                                tenant.status = TenantStatus.DKIM_ENABLED
                            tenant.setup_error = None
                        
                        domain = await bg_db.execute(
                            select(Domain).where(Domain.name == result["domain_name"])
                        )
                        domain = domain.scalar_one_or_none()
                        if domain:
                            domain.dkim_enabled = result.get("dkim_enabled", False)
                            if result.get("dkim_enabled"):
                                domain.status = DomainStatus.ACTIVE
                
                await bg_db.commit()
                
        except Exception as e:
            step5_jobs[job_id]["status"] = "error"
            step5_jobs[job_id]["error"] = str(e)
    
    background_tasks.add_task(run_parallel)
    
    # Estimate time: With parallel processing, much faster
    # 3 browsers x (5 min per domain + 10 min DNS wait average) / 3 = ~5 min per domain
    estimated_minutes = (len(tenants_data) / 3) * 5
    
    return {
        "success": True,
        "job_id": job_id,
        "mode": "parallel",
        "max_browsers": 3,
        "message": f"Started PARALLEL Step 5 automation for {len(tenants_data)} tenants (3 browsers)",
        "total_tenants": len(tenants_data),
        "estimated_minutes": round(estimated_minutes),
        "note": "Parallel mode processes 3 domains simultaneously with intelligent DNS wait handling"
    }


@router.post("/batches/{batch_id}/step5/retry-failed")
async def retry_failed_tenants(
    batch_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """Retry Step 5 for all failed tenants in batch."""
    result = await db.execute(
        select(Tenant).where(
            Tenant.batch_id == batch_id,
            Tenant.domain_id.isnot(None),
            Tenant.setup_error.isnot(None),
            Tenant.dkim_enabled != True
        )
    )
    failed_tenants = result.scalars().all()
    
    if not failed_tenants:
        return {
            "success": True,
            "message": "No failed tenants to retry"
        }
    
    # Clear errors for retry
    for tenant in failed_tenants:
        tenant.setup_error = None
    await db.commit()
    
    job_id = f"{batch_id}_retry"
    
    step5_jobs[job_id] = {
        "status": "running",
        "total": len(failed_tenants),
        "completed": 0,
        "successful": 0,
        "failed": 0,
        "started_at": datetime.utcnow().isoformat()
    }
    
    async def run_retry():
        try:
            from app.db.session import async_engine
            async with AsyncSession(async_engine, expire_on_commit=False) as bg_db:
                for i, tenant in enumerate(failed_tenants):
                    result = await run_step5_for_tenant(bg_db, tenant.id)
                    
                    step5_jobs[job_id]["completed"] = i + 1
                    if result.success:
                        step5_jobs[job_id]["successful"] += 1
                    else:
                        step5_jobs[job_id]["failed"] += 1
                
                step5_jobs[job_id]["status"] = "completed"
                step5_jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()
                
        except Exception as e:
            step5_jobs[job_id]["status"] = "error"
            step5_jobs[job_id]["error"] = str(e)
    
    background_tasks.add_task(run_retry)
    
    return {
        "success": True,
        "job_id": job_id,
        "message": f"Retrying {len(failed_tenants)} failed tenants"
    }


# =============================================================================
# STEP 6: MAILBOX CREATION ENDPOINTS
# =============================================================================


@router.get("/batches/{batch_id}/step6/status")
async def get_step6_status(
    batch_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get Step 6 status for all tenants in batch."""

    # Get batch info
    batch_result = await db.execute(
        select(SetupBatch).where(SetupBatch.id == batch_id)
    )
    batch = batch_result.scalar_one_or_none()
    if not batch:
        raise HTTPException(404, "Batch not found")

    # Get tenants with mailbox counts
    result = await db.execute(
        select(Tenant).where(Tenant.batch_id == batch_id)
    )
    tenants = result.scalars().all()

    tenant_statuses = []
    for tenant in tenants:
        # Count mailboxes for this tenant
        mailbox_result = await db.execute(
            select(func.count(Mailbox.id)).where(Mailbox.tenant_id == tenant.id)
        )
        mailbox_count = mailbox_result.scalar() or 0

        # Get live progress if available
        live_progress = get_step6_progress(str(tenant.id))

        tenant_statuses.append(
            {
                "tenant_id": str(tenant.id),
                "name": tenant.name,
                "domain": tenant.custom_domain,
                "onmicrosoft_domain": tenant.onmicrosoft_domain,
                "step5_complete": tenant.domain_verified_in_m365 and tenant.dkim_enabled,
                "step6_started": tenant.step6_started,
                "step6_complete": tenant.step6_complete,
                "step6_error": tenant.step6_error,
                "licensed_user": tenant.licensed_user_upn,
                "mailbox_count": mailbox_count,
                "progress": {
                    "mailboxes_created": tenant.step6_mailboxes_created,
                    "display_names_fixed": tenant.step6_display_names_fixed,
                    "accounts_enabled": tenant.step6_accounts_enabled,
                    "passwords_set": tenant.step6_passwords_set,
                    "upns_fixed": tenant.step6_upns_fixed,
                    "delegations_done": tenant.step6_delegations_done,
                },
                "live_progress": {
                    "step": live_progress.get("step", ""),
                    "status": live_progress.get("status", ""),
                    "detail": live_progress.get("detail", ""),
                    "active": bool(live_progress),
                },
            }
        )

    # Summary stats
    total = len(tenants)
    step5_complete = sum(1 for t in tenant_statuses if t["step5_complete"])
    step6_complete = sum(1 for t in tenant_statuses if t["step6_complete"])
    step6_errors = sum(1 for t in tenant_statuses if t["step6_error"])

    return {
        "batch_id": str(batch_id),
        "display_name": f"{batch.persona_first_name or ''} {batch.persona_last_name or ''}".strip()
        or None,
        "summary": {
            "total_tenants": total,
            "step5_complete": step5_complete,
            "step6_complete": step6_complete,
            "step6_errors": step6_errors,
            "ready_for_step6": step5_complete - step6_complete - step6_errors,
        },
        "tenants": tenant_statuses,
    }


@router.post("/batches/{batch_id}/step6/start")
async def start_step6_automation(
    batch_id: UUID,
    request: dict,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Start Step 6 automation for a batch."""

    display_name = request.get("display_name", "").strip()
    if not display_name or " " not in display_name:
        raise HTTPException(
            400, "Display name must include first and last name (e.g., 'Jack Zuvelek')"
        )

    # Verify batch exists
    batch_result = await db.execute(
        select(SetupBatch).where(SetupBatch.id == batch_id)
    )
    batch = batch_result.scalar_one_or_none()
    if not batch:
        raise HTTPException(404, "Batch not found")

    # Check if there are eligible tenants
    tenant_result = await db.execute(
        select(func.count(Tenant.id)).where(
            Tenant.batch_id == batch_id,
            Tenant.domain_verified_in_m365 == True,
            Tenant.step6_complete == False,
        )
    )
    eligible_count = tenant_result.scalar() or 0

    if eligible_count == 0:
        raise HTTPException(
            400, "No eligible tenants for Step 6 (need Step 5 complete, Step 6 not complete)"
        )

    # Start automation in background
    background_tasks.add_task(run_step6_for_batch, batch_id, display_name, db)

    return {
        "success": True,
        "message": f"Started Step 6 for {eligible_count} tenant(s)",
        "display_name": display_name,
    }


@router.get("/batches/{batch_id}/step6/automation-status")
async def get_step6_automation_status(
    batch_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get real-time automation status for Step 6."""

    # Get tenants
    result = await db.execute(
        select(Tenant).where(Tenant.batch_id == batch_id)
    )
    tenants = result.scalars().all()

    # Get live progress
    all_progress = get_step6_all_progress()

    statuses = []
    for tenant in tenants:
        progress = all_progress.get(str(tenant.id), {})
        statuses.append(
            {
                "tenant_id": str(tenant.id),
                "domain": tenant.custom_domain,
                "step": progress.get("step", ""),
                "status": progress.get("status", ""),
                "detail": progress.get("detail", ""),
                "db_complete": tenant.step6_complete,
                "db_error": tenant.step6_error,
            }
        )

    # Count active
    active = sum(1 for s in statuses if s["status"] == "in_progress")
    complete = sum(1 for s in statuses if s["db_complete"])
    errors = sum(1 for s in statuses if s["db_error"])

    return {
        "active": active,
        "complete": complete,
        "errors": errors,
        "total": len(tenants),
        "tenants": statuses,
    }


@router.get("/batches/{batch_id}/step6/export-csv")
async def export_mailboxes_csv(
    batch_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Export all mailboxes as CSV (DisplayName,EmailAddress,Password)."""
    from fastapi.responses import StreamingResponse
    import csv
    import io

    # Get batch for display name
    batch_result = await db.execute(
        select(SetupBatch).where(SetupBatch.id == batch_id)
    )
    batch = batch_result.scalar_one_or_none()
    if not batch:
        raise HTTPException(404, "Batch not found")

    display_name = f"{batch.persona_first_name or ''} {batch.persona_last_name or ''}".strip()

    # Get all tenants with their mailboxes
    result = await db.execute(
        select(Tenant)
        .where(Tenant.batch_id == batch_id)
        .options(selectinload(Tenant.mailboxes))
    )
    tenants = result.scalars().all()

    # Build CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["DisplayName", "EmailAddress", "Password"])

    for tenant in tenants:
        # First row: Licensed user (me1)
        if tenant.licensed_user_upn:
            writer.writerow(
                [
                    display_name or "Licensed User",
                    tenant.licensed_user_upn,
                    tenant.licensed_user_password or "#Sendemails1",
                ]
            )

        # Mailboxes
        for mailbox in tenant.mailboxes:
            writer.writerow(
                [
                    mailbox.display_name,
                    mailbox.email,
                    mailbox.password,
                ]
            )

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=mailboxes_batch_{batch_id}.csv"
        },
    )


@router.post("/tenants/{tenant_id}/step6/retry")
async def retry_step6_for_tenant(
    tenant_id: UUID,
    request: dict,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Retry Step 6 for a single tenant."""

    display_name = request.get("display_name", "").strip()
    if not display_name:
        raise HTTPException(400, "Display name required")

    # Get tenant
    result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    # Reset step 6 status
    tenant.step6_started = False
    tenant.step6_complete = False
    tenant.step6_error = None
    await db.commit()

    # Prepare tenant data
    tenant_data = {
        "id": str(tenant.id),
        "name": tenant.name,
        "custom_domain": tenant.custom_domain,
        "onmicrosoft_domain": tenant.onmicrosoft_domain,
        "admin_email": tenant.admin_email,
        "admin_password": tenant.admin_password,
        "totp_secret": tenant.totp_secret,
    }

    # Run in background
    from app.services.mailbox_setup import run_step6_for_tenant_sync

    background_tasks.add_task(run_step6_for_tenant_sync, tenant_data, display_name)

    return {
        "success": True,
        "message": f"Retrying Step 6 for {tenant.custom_domain}",
    }


@router.post("/batches/{batch_id}/step6/generate-mailboxes", response_model=StepResult)
async def batch_generate_mailboxes(
    batch_id: UUID,
    first_name: str = Form(...),
    last_name: str = Form(...),
    count: int = Form(default=50),
    db: AsyncSession = Depends(get_db)
):
    """Step 6a: Generate mailboxes for all tenants in this batch."""
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    # Save persona to batch
    batch.persona_first_name = first_name
    batch.persona_last_name = last_name
    batch.mailboxes_per_tenant = count
    
    result = await db.execute(
        select(Tenant).where(Tenant.batch_id == batch_id, Tenant.domain_id.isnot(None))
    )
    tenants = result.scalars().all()
    
    if not tenants:
        return StepResult(success=False, message="No tenants with linked domains", details={})
    
    total_generated = 0
    
    for tenant in tenants:
        domain_result = await db.execute(select(Domain).where(Domain.id == tenant.domain_id))
        domain = domain_result.scalar_one_or_none()
        if not domain:
            continue
        
        mailbox_data = generate_email_addresses(first_name, last_name, domain.name, count)
        
        for mb_data in mailbox_data:
            existing = await db.execute(select(Mailbox).where(Mailbox.email == mb_data['email']))
            if existing.scalar_one_or_none():
                continue
            
            mailbox = Mailbox(
                email=mb_data['email'],
                display_name=mb_data['display_name'],
                password=mb_data['password'],
                tenant_id=tenant.id,
                batch_id=batch_id,  # Link to batch
                status=MailboxStatus.PENDING,
                warmup_stage='none',
            )
            db.add(mailbox)
            total_generated += 1
    
    await db.commit()
    
    return StepResult(
        success=True,
        message=f"Generated {total_generated} mailboxes for {len(tenants)} tenants",
        details={"mailboxes_generated": total_generated, "tenants_processed": len(tenants)}
    )


@router.post("/batches/{batch_id}/step6/create-mailboxes", response_model=StepResult)
async def batch_create_mailboxes(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """Step 6b: Create mailboxes in M365."""
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    if batch.current_step == 6:
        batch.current_step = 7
        batch.status = BatchStatus.COMPLETED
        batch.completed_at = datetime.utcnow()
        await db.commit()
    
    return StepResult(
        success=True,
        message="Mailbox creation - implementation pending",
        details={"note": "Requires PowerShell integration"}
    )


@router.get("/batches/{batch_id}/step6/export-credentials")
async def batch_export_credentials(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """Export credentials for this batch."""
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    result = await db.execute(select(Mailbox).where(Mailbox.batch_id == batch_id))
    mailboxes = result.scalars().all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["DisplayName", "EmailAddress", "Password"])
    
    for mb in mailboxes:
        writer.writerow([mb.display_name, mb.email, mb.password])
    
    output.seek(0)
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={batch.name}_credentials.csv"}
    )


@router.get("/batches/{batch_id}/step6/script/create-mailboxes/{tenant_id}")
async def get_create_mailboxes_script(batch_id: UUID, tenant_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get mailbox creation script for one tenant."""
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    mailboxes = (await db.execute(
        select(Mailbox).where(Mailbox.tenant_id == tenant_id)
    )).scalars().all()
    
    if not mailboxes:
        raise HTTPException(status_code=404, detail="No mailboxes found for this tenant")
    
    mailbox_data = [
        {"display_name": m.display_name, "email": m.email, "password": m.password}
        for m in mailboxes
    ]
    
    script = mailbox_scripts.generate_master_script(
        tenant.microsoft_tenant_id,
        tenant.licensed_user_upn or tenant.admin_email,
        mailbox_data
    )
    
    return PlainTextResponse(script, media_type="text/plain")


@router.post("/batches/{batch_id}/step6/mark-created/{tenant_id}")
async def mark_mailboxes_created(batch_id: UUID, tenant_id: UUID, db: AsyncSession = Depends(get_db)):
    """Mark mailboxes as created after running the PowerShell script."""
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    tenant.mailboxes_created = True
    tenant.mailboxes_created_at = datetime.utcnow()
    tenant.delegation_completed = True
    tenant.status = TenantStatus.READY
    
    # Update mailbox statuses to CREATED
    await db.execute(
        update(Mailbox).where(Mailbox.tenant_id == tenant_id).values(status=MailboxStatus.CREATED)
    )
    
    await db.commit()
    return {"success": True}


# ============== LEGACY STATUS ENDPOINT (backward compatibility) ==============

@router.get("/status", response_model=WizardStatus)
async def get_wizard_status(db: AsyncSession = Depends(get_db)):
    """
    Get current wizard progress. Determines which step user is on based on data state.
    """
    # Count domains
    domains_total = (await db.execute(select(func.count(Domain.id)))).scalar() or 0
    
    zones_created = (await db.execute(
        select(func.count(Domain.id)).where(Domain.cloudflare_zone_id.isnot(None))
    )).scalar() or 0
    
    zones_pending = domains_total - zones_created
    
    ns_propagated = (await db.execute(
        select(func.count(Domain.id)).where(Domain.status == DomainStatus.NS_PROPAGATED)
    )).scalar() or 0
    
    ns_pending = zones_created - ns_propagated
    
    redirects_configured = (await db.execute(
        select(func.count(Domain.id)).where(Domain.redirect_configured == True)
    )).scalar() or 0
    
    # Count tenants
    tenants_total = (await db.execute(select(func.count(Tenant.id)))).scalar() or 0
    
    tenants_linked = (await db.execute(
        select(func.count(Tenant.id)).where(Tenant.domain_id.isnot(None))
    )).scalar() or 0
    
    tenants_m365_verified = (await db.execute(
        select(func.count(Tenant.id)).where(Tenant.status == TenantStatus.DOMAIN_VERIFIED)
    )).scalar() or 0
    
    tenants_dkim_enabled = (await db.execute(
        select(func.count(Tenant.id)).where(Tenant.status == TenantStatus.DKIM_ENABLED)
    )).scalar() or 0
    
    # Count mailboxes
    mailboxes_total = (await db.execute(select(func.count(Mailbox.id)))).scalar() or 0
    
    mailboxes_pending = (await db.execute(
        select(func.count(Mailbox.id)).where(Mailbox.status == MailboxStatus.PENDING)
    )).scalar() or 0
    
    mailboxes_ready = (await db.execute(
        select(func.count(Mailbox.id)).where(Mailbox.status == MailboxStatus.READY)
    )).scalar() or 0
    
    # Determine current step
    if domains_total == 0:
        current_step = 1
        step_name = "Import Domains"
        can_proceed = False
    elif zones_created == 0:
        current_step = 2
        step_name = "Create Zones"
        can_proceed = True
    elif ns_propagated == 0 and redirects_configured == 0:
        current_step = 3
        step_name = "Verify Nameservers"
        can_proceed = True
    elif tenants_total == 0:
        current_step = 4
        step_name = "Import Tenants"
        can_proceed = True
    elif tenants_dkim_enabled == 0:
        current_step = 5
        step_name = "Email Setup"
        can_proceed = tenants_linked > 0
    elif mailboxes_ready == 0:
        current_step = 6
        step_name = "Create Mailboxes"
        can_proceed = tenants_dkim_enabled > 0
    else:
        current_step = 7
        step_name = "Complete"
        can_proceed = False
    
    return WizardStatus(
        current_step=current_step,
        step_name=step_name,
        can_proceed=can_proceed,
        domains_total=domains_total,
        domains_imported=domains_total > 0,
        zones_created=zones_created,
        zones_pending=zones_pending,
        ns_propagated=ns_propagated,
        ns_pending=ns_pending,
        redirects_configured=redirects_configured,
        tenants_total=tenants_total,
        tenants_linked=tenants_linked,
        tenants_m365_verified=tenants_m365_verified,
        tenants_dkim_enabled=tenants_dkim_enabled,
        mailboxes_total=mailboxes_total,
        mailboxes_pending=mailboxes_pending,
        mailboxes_ready=mailboxes_ready,
    )


# ============== STEP 1: DOMAINS ==============

@router.post("/step1/import-domains", response_model=StepResult)
async def wizard_import_domains(
    file: UploadFile = File(...),
    redirect_url: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Step 1: Import domains from CSV and set redirect URL for all.
    
    CSV format: domain_name,registrar,registration_date
    """
    try:
        content = await file.read()
        decoded = content.decode('utf-8')
        reader = csv.DictReader(io.StringIO(decoded))
        
        created = 0
        skipped = 0
        errors = []
        
        for row in reader:
            domain_name = row.get('domain_name', '').strip().lower()
            if not domain_name:
                continue
            
            # Check if exists
            existing = await db.execute(
                select(Domain).where(Domain.name == domain_name)
            )
            if existing.scalar_one_or_none():
                skipped += 1
                continue
            
            # Extract TLD
            parts = domain_name.split('.')
            tld = parts[-1] if len(parts) > 1 else ''
            
            # Create domain with redirect URL
            domain = Domain(
                name=domain_name,
                tld=tld,
                status=DomainStatus.PURCHASED,
                redirect_url=redirect_url,
                cloudflare_zone_status='none',
            )
            db.add(domain)
            created += 1
        
        await db.commit()
        
        return StepResult(
            success=True,
            message=f"Imported {created} domains, skipped {skipped} duplicates",
            details={"created": created, "skipped": skipped, "redirect_url": redirect_url}
        )
    
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


# ============== STEP 2: CREATE ZONES ==============

@router.post("/step2/create-zones", response_model=StepResult)
async def wizard_create_zones(db: AsyncSession = Depends(get_db)):
    """
    Step 2: Create Cloudflare zones for all imported domains.
    Returns nameserver groups for display.
    """
    try:
        # Get domains without zones
        result = await db.execute(
            select(Domain).where(Domain.cloudflare_zone_id.is_(None))
        )
        domains = result.scalars().all()
        
        if not domains:
            return StepResult(
                success=True,
                message="All domains already have zones",
                details={"created": 0}
            )
        
        success_count = 0
        failed_count = 0
        ns_groups = {}
        
        for domain in domains:
            try:
                # Create zone
                zone_result = await cloudflare_service.create_zone(domain.name)
                
                if zone_result.get('zone_id'):
                    domain.cloudflare_zone_id = zone_result['zone_id']
                    domain.cloudflare_nameservers = zone_result['nameservers']
                    domain.cloudflare_zone_status = 'pending'
                    domain.status = DomainStatus.ZONE_CREATED
                    
                    # Create Phase 1 DNS (CNAME + DMARC)
                    await cloudflare_service.create_phase1_dns(
                        zone_result['zone_id'], 
                        domain.name
                    )
                    domain.phase1_cname_added = True
                    domain.phase1_dmarc_added = True
                    
                    success_count += 1
                    
                    # Group by nameservers
                    ns_key = tuple(sorted(zone_result['nameservers']))
                    if ns_key not in ns_groups:
                        ns_groups[ns_key] = []
                    ns_groups[ns_key].append(domain.name)
                else:
                    failed_count += 1
                    domain.error_message = zone_result.get('error', 'Unknown error')
            
            except Exception as e:
                failed_count += 1
                domain.error_message = str(e)
        
        await db.commit()
        
        # Format NS groups for response
        nameserver_groups = [
            {
                "nameservers": list(ns),
                "domain_count": len(domains_list),
                "domains": domains_list
            }
            for ns, domains_list in ns_groups.items()
        ]
        
        return StepResult(
            success=True,
            message=f"Created {success_count} zones, {failed_count} failed",
            details={
                "success": success_count,
                "failed": failed_count,
                "nameserver_groups": nameserver_groups
            }
        )
    
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ============== STEP 3: PROPAGATION & REDIRECTS ==============

@router.post("/step3/check-propagation", response_model=StepResult)
async def wizard_check_propagation(db: AsyncSession = Depends(get_db)):
    """
    Step 3a: Check NS propagation for all domains with zones.
    """
    try:
        result = await db.execute(
            select(Domain).where(
                Domain.cloudflare_zone_id.isnot(None),
                Domain.status == DomainStatus.ZONE_CREATED
            )
        )
        domains = result.scalars().all()
        
        propagated = 0
        pending = 0
        
        for domain in domains:
            if domain.cloudflare_nameservers:
                is_propagated = await cloudflare_service.check_ns_propagation(
                    domain.name,
                    domain.cloudflare_nameservers
                )
                
                if is_propagated:
                    domain.status = DomainStatus.NS_PROPAGATED
                    from datetime import datetime
                    domain.ns_propagated_at = datetime.utcnow()
                    propagated += 1
                else:
                    pending += 1
        
        await db.commit()
        
        return StepResult(
            success=True,
            message=f"{propagated} propagated, {pending} still pending",
            details={"propagated": propagated, "pending": pending}
        )
    
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/step3/setup-redirects", response_model=StepResult)
async def wizard_setup_redirects(db: AsyncSession = Depends(get_db)):
    """
    Step 3b: Setup Cloudflare redirect rules for all domains with zones.
    """
    try:
        result = await db.execute(
            select(Domain).where(
                Domain.cloudflare_zone_id.isnot(None),
                Domain.redirect_url.isnot(None),
                Domain.redirect_configured == False
            )
        )
        domains = result.scalars().all()
        
        success_count = 0
        failed_count = 0
        
        for domain in domains:
            try:
                result = await cloudflare_service.create_redirect_rule(
                    domain.cloudflare_zone_id,
                    domain.name,
                    domain.redirect_url
                )
                
                if result.get('success'):
                    domain.redirect_configured = True
                    success_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                failed_count += 1
                domain.error_message = str(e)
        
        await db.commit()
        
        return StepResult(
            success=True,
            message=f"Setup {success_count} redirects, {failed_count} failed",
            details={"success": success_count, "failed": failed_count}
        )
    
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ============== STEP 4: TENANTS ==============

@router.post("/step4/import-tenants", response_model=StepResult)
async def wizard_import_tenants(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Step 4: Import tenants from CSV and auto-link to domains.
    
    CSV format: tenant_name,microsoft_tenant_id,onmicrosoft_domain,admin_email,admin_password,provider,licensed_user_upn,domain_name
    """
    try:
        content = await file.read()
        decoded = content.decode('utf-8')
        reader = csv.DictReader(io.StringIO(decoded))
        
        created = 0
        linked = 0
        skipped = 0
        
        for row in reader:
            tenant_name = row.get('tenant_name', '').strip()
            microsoft_tenant_id = row.get('microsoft_tenant_id', '').strip()
            
            if not tenant_name or not microsoft_tenant_id:
                continue
            
            # Check if exists
            existing = await db.execute(
                select(Tenant).where(Tenant.microsoft_tenant_id == microsoft_tenant_id)
            )
            if existing.scalar_one_or_none():
                skipped += 1
                continue
            
            # Create tenant
            tenant = Tenant(
                name=tenant_name,
                microsoft_tenant_id=microsoft_tenant_id,
                onmicrosoft_domain=row.get('onmicrosoft_domain', '').strip(),
                admin_email=row.get('admin_email', '').strip(),
                admin_password=row.get('admin_password', '').strip(),
                provider=row.get('provider', '').strip(),
                licensed_user_upn=row.get('licensed_user_upn', '').strip() or row.get('licensed_user_email', '').strip(),
                status=TenantStatus.IMPORTED
            )
            
            # Auto-link to domain if specified
            domain_name = row.get('domain_name', '').strip().lower()
            if domain_name:
                domain_result = await db.execute(
                    select(Domain).where(Domain.name == domain_name)
                )
                domain = domain_result.scalar_one_or_none()
                if domain:
                    tenant.domain_id = domain.id
                    domain.tenant_id = tenant.id
                    domain.status = DomainStatus.TENANT_LINKED
                    tenant.status = TenantStatus.DOMAIN_LINKED
                    linked += 1
            
            db.add(tenant)
            created += 1
        
        await db.commit()
        
        return StepResult(
            success=True,
            message=f"Imported {created} tenants, {linked} linked to domains, {skipped} skipped",
            details={"created": created, "linked": linked, "skipped": skipped}
        )
    
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


# ============== STEP 5: M365 & DKIM ==============

@router.post("/step5/setup-m365", response_model=StepResult)
async def wizard_setup_m365(db: AsyncSession = Depends(get_db)):
    """
    Step 5a: Add domains to M365, verify, and setup DNS.
    
    Note: This is a placeholder - actual M365 integration requires
    the microsoft service and powershell service to be implemented.
    """
    # TODO: Implement when microsoft_service is ready
    return StepResult(
        success=True,
        message="M365 setup - implementation pending",
        details={"note": "Requires Microsoft Graph API integration"}
    )


@router.post("/step5/setup-dkim", response_model=StepResult)
async def wizard_setup_dkim(db: AsyncSession = Depends(get_db)):
    """
    Step 5b: Setup DKIM for all verified tenants.
    
    Note: This is a placeholder - actual DKIM setup requires
    PowerShell scripts to be executed.
    """
    # TODO: Implement when powershell_service is ready
    return StepResult(
        success=True,
        message="DKIM setup - implementation pending",
        details={"note": "Requires PowerShell integration"}
    )


# ============== STEP 6: MAILBOXES ==============

@router.post("/step6/generate-mailboxes", response_model=StepResult)
async def wizard_generate_mailboxes(
    first_name: str = Form(...),
    last_name: str = Form(...),
    count: int = Form(default=50),
    db: AsyncSession = Depends(get_db)
):
    """
    Step 6a: Generate mailbox records for ALL tenants with same persona.
    NO NUMBERS in email addresses!
    """
    try:
        # Get all tenants with DKIM enabled (or at minimum, linked domains)
        result = await db.execute(
            select(Tenant).where(
                Tenant.domain_id.isnot(None)
            )
        )
        tenants = result.scalars().all()
        
        if not tenants:
            return StepResult(
                success=False,
                message="No tenants with linked domains found",
                details={}
            )
        
        total_generated = 0
        
        for tenant in tenants:
            # Get domain name
            domain_result = await db.execute(
                select(Domain).where(Domain.id == tenant.domain_id)
            )
            domain = domain_result.scalar_one_or_none()
            
            if not domain:
                continue
            
            # Generate email variations (NO NUMBERS!)
            mailbox_data = generate_email_addresses(
                first_name=first_name,
                last_name=last_name,
                domain=domain.name,
                count=count
            )
            
            # Create mailbox records
            for mb_data in mailbox_data:
                # Check if already exists
                existing = await db.execute(
                    select(Mailbox).where(Mailbox.email == mb_data['email'])
                )
                if existing.scalar_one_or_none():
                    continue
                
                mailbox = Mailbox(
                    email=mb_data['email'],
                    display_name=mb_data['display_name'],
                    password=mb_data['password'],
                    tenant_id=tenant.id,
                    status=MailboxStatus.PENDING,
                    warmup_stage='none',
                )
                db.add(mailbox)
                total_generated += 1
        
        await db.commit()
        
        return StepResult(
            success=True,
            message=f"Generated {total_generated} mailboxes across {len(tenants)} tenants",
            details={
                "mailboxes_generated": total_generated,
                "tenants_processed": len(tenants),
                "persona": f"{first_name} {last_name}"
            }
        )
    
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/step6/create-mailboxes", response_model=StepResult)
async def wizard_create_mailboxes(db: AsyncSession = Depends(get_db)):
    """
    Step 6b: Create pending mailboxes in M365 and configure.
    
    Note: This is a placeholder - actual mailbox creation requires
    PowerShell scripts to be executed.
    """
    # TODO: Implement when powershell_service is ready
    return StepResult(
        success=True,
        message="Mailbox creation - implementation pending",
        details={"note": "Requires PowerShell integration"}
    )


@router.get("/step6/export-credentials")
async def wizard_export_credentials(db: AsyncSession = Depends(get_db)):
    """
    Step 6c: Export all mailbox credentials as CSV.
    
    Format: DisplayName,EmailAddress,Password
    """
    result = await db.execute(select(Mailbox))
    mailboxes = result.scalars().all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["DisplayName", "EmailAddress", "Password"])
    
    for mb in mailboxes:
        writer.writerow([mb.display_name, mb.email, mb.password])
    
    output.seek(0)
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=mailbox_credentials.csv"}
    )