"""
Domain Removal API Endpoints

Two modes:
  POST /validate-db     — Validate domains from database
  POST /validate-csv    — Validate domains from CSV upload
  POST /remove-db       — Remove domains using DB records (background job)
  POST /remove-csv      — Remove domains using CSV credentials (background job)
  GET  /jobs/{job_id}   — Check bulk removal progress
  GET  /jobs            — List all removal jobs
  GET  /csv-template    — Download CSV template

Repair/diagnostic:
  GET  /orphaned-domains — Find domains incorrectly unlinked from tenants
  POST /repair-links     — Re-link domains to their tenants
"""
import asyncio
import io
import re
import uuid as uuid_mod
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db_session, async_engine, SessionLocal
from app.models.domain import Domain, DomainStatus
from app.models.tenant import Tenant
from app.services.domain_removal_service import domain_removal_service

router = APIRouter(prefix="/api/v1/domain-removal", tags=["domain-removal"])


# ===== Request/Response Models =====

class DBRemovalRequest(BaseModel):
    domains: List[str]
    skip_m365: bool = False
    headless: bool = False
    stagger_seconds: int = 10
    max_retries: int = 2  # Number of retries for M365 removal (0 = no retries, just 1 attempt)


class DBValidationRequest(BaseModel):
    domains: List[str]


# ===== In-memory job tracking =====
removal_jobs = {}


# ===== CSV Template =====

@router.get("/csv-template")
async def download_csv_template():
    """Download a CSV template for external domain removal."""
    content = "domain,admin_email,admin_password,totp_secret\n"
    content += "example.com,admin@contoso.onmicrosoft.com,Password123,\n"
    content += "example2.com,admin@fabrikam.onmicrosoft.com,Pass456!,JBSWY3DPEHPK3PXP\n"
    return StreamingResponse(
        io.BytesIO(content.encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=domain_removal_template.csv"}
    )


# ===== Validation Endpoints =====

@router.post("/validate-db")
async def validate_db_domains(
    request: DBValidationRequest,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Validate domains from the database before removal.
    
    Checks that each domain exists in the DB, is linked to a tenant,
    and gathers tenant/mailbox/Cloudflare info for review.
    """
    if not request.domains:
        raise HTTPException(status_code=400, detail="No domains provided")
    
    return await domain_removal_service.validate_domains_from_db(db, request.domains)


@router.post("/validate-csv")
async def validate_csv_domains(file: UploadFile = File(...)):
    """
    Validate domains from a CSV upload before removal.
    
    Parses the CSV and checks that required fields are present.
    """
    content = await file.read()
    try:
        csv_text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        csv_text = content.decode("latin-1")
    
    entries = domain_removal_service.parse_removal_csv(csv_text)
    if not entries:
        raise HTTPException(
            status_code=400,
            detail="No valid entries found. Required columns: domain, admin_email, admin_password"
        )
    
    return domain_removal_service.validate_csv_entries(entries)


# ===== Removal Endpoints =====

@router.post("/remove-db")
async def remove_db_domains(
    request: DBRemovalRequest,
    background_tasks: BackgroundTasks,
):
    """
    Start background removal of domains using database records (Mode 1).
    
    Returns a job_id to poll for progress.
    """
    if not request.domains:
        raise HTTPException(status_code=400, detail="No domains provided")
    
    job_id = str(uuid_mod.uuid4())
    removal_jobs[job_id] = {
        "id": job_id,
        "mode": "database",
        "status": "running",
        "started_at": datetime.utcnow().isoformat(),
        "total": len(request.domains),
        "completed": 0,
        "successful": 0,
        "failed": 0,
        "domains": request.domains,
        "results": []
    }
    
    async def run():
        async with SessionLocal() as bg_db:
            for i, dn in enumerate(request.domains):
                try:
                    r = await domain_removal_service.remove_domain_from_db(
                        db=bg_db,
                        domain_name=dn,
                        skip_m365=request.skip_m365,
                        headless=request.headless,
                        max_retries=request.max_retries
                    )
                    removal_jobs[job_id]["results"].append(r)
                    removal_jobs[job_id]["completed"] = i + 1
                    if r["success"]:
                        removal_jobs[job_id]["successful"] += 1
                    else:
                        removal_jobs[job_id]["failed"] += 1
                    
                    if i < len(request.domains) - 1:
                        await asyncio.sleep(request.stagger_seconds)
                except Exception as e:
                    removal_jobs[job_id]["results"].append({
                        "domain": dn,
                        "success": False,
                        "error": str(e)
                    })
                    removal_jobs[job_id]["completed"] = i + 1
                    removal_jobs[job_id]["failed"] += 1
            
            removal_jobs[job_id]["status"] = "completed"
            removal_jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()
    
    background_tasks.add_task(run)
    return {
        "job_id": job_id,
        "status": "started",
        "total_domains": len(request.domains)
    }


@router.post("/remove-csv")
async def remove_csv_domains(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    skip_m365: bool = Form(False),
    headless: bool = Form(False),
    stagger_seconds: int = Form(10)
):
    """
    Start background removal of domains from CSV upload (Mode 2).
    
    Returns a job_id to poll for progress.
    """
    content = await file.read()
    try:
        csv_text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        csv_text = content.decode("latin-1")
    
    entries = domain_removal_service.parse_removal_csv(csv_text)
    if not entries:
        raise HTTPException(
            status_code=400,
            detail="No valid entries found in CSV"
        )
    
    job_id = str(uuid_mod.uuid4())
    removal_jobs[job_id] = {
        "id": job_id,
        "mode": "csv",
        "status": "running",
        "started_at": datetime.utcnow().isoformat(),
        "total": len(entries),
        "completed": 0,
        "successful": 0,
        "failed": 0,
        "domains": [e["domain"] for e in entries],
        "results": []
    }
    
    async def run():
        async with SessionLocal() as bg_db:
            for i, entry in enumerate(entries):
                try:
                    r = await domain_removal_service.remove_domain_from_csv(
                        entry=entry,
                        db=bg_db,
                        skip_m365=skip_m365,
                        headless=headless
                    )
                    removal_jobs[job_id]["results"].append(r)
                    removal_jobs[job_id]["completed"] = i + 1
                    if r["success"]:
                        removal_jobs[job_id]["successful"] += 1
                    else:
                        removal_jobs[job_id]["failed"] += 1
                    
                    if i < len(entries) - 1:
                        await asyncio.sleep(stagger_seconds)
                except Exception as e:
                    removal_jobs[job_id]["results"].append({
                        "domain": entry["domain"],
                        "success": False,
                        "error": str(e)
                    })
                    removal_jobs[job_id]["completed"] = i + 1
                    removal_jobs[job_id]["failed"] += 1
            
            removal_jobs[job_id]["status"] = "completed"
            removal_jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()
    
    background_tasks.add_task(run)
    return {
        "job_id": job_id,
        "status": "started",
        "total_domains": len(entries)
    }


# ===== Job Status Endpoints =====

@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Get the status and results of a domain removal job."""
    if job_id not in removal_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return removal_jobs[job_id]


@router.get("/jobs")
async def list_jobs():
    """List all domain removal jobs (without full results for brevity)."""
    return {
        "jobs": [
            {k: v for k, v in j.items() if k != "results"}
            for j in removal_jobs.values()
        ]
    }


# ===== Repair / Diagnostic Endpoints =====

@router.get("/orphaned-domains")
async def get_orphaned_domains(
    db: AsyncSession = Depends(get_db_session)
):
    """
    Find domains that were incorrectly unlinked from tenants by the old buggy removal code.
    
    These are domains with:
    - status = PURCHASED and tenant_id = NULL
    - error_message containing "Removed from tenant" (set by the old code that wiped DB regardless)
    
    Also finds domains with status = PROBLEM (failed M365 removal, new code preserves the link).
    
    Returns the list with the tenant name extracted from the error message so you know
    which tenant to re-link them to.
    """
    # Find domains that were incorrectly unlinked (old bug: status=PURCHASED, no tenant, "Removed from tenant" in error)
    orphaned_result = await db.execute(
        select(Domain).where(
            Domain.status == DomainStatus.PURCHASED,
            Domain.tenant_id.is_(None),
            Domain.error_message.ilike("%Removed from tenant%")
        )
    )
    orphaned_domains = orphaned_result.scalars().all()
    
    # Also find domains with PROBLEM status (new code: M365 failed, link preserved)
    problem_result = await db.execute(
        select(Domain).options(selectinload(Domain.tenant)).where(
            Domain.status == DomainStatus.PROBLEM,
            Domain.error_message.ilike("%M365 removal failed%")
        )
    )
    problem_domains = problem_result.scalars().all()
    
    orphaned_list = []
    for d in orphaned_domains:
        # Extract tenant name from error_message: "Removed from tenant 'TenantName' at ..."
        tenant_name = None
        if d.error_message:
            match = re.search(r"Removed from tenant '([^']+)'", d.error_message)
            if match:
                tenant_name = match.group(1)
        
        # Try to find the tenant by name to get its ID for easy re-linking
        suggested_tenant = None
        if tenant_name:
            tenant_result = await db.execute(
                select(Tenant).where(Tenant.name == tenant_name)
            )
            tenant = tenant_result.scalar_one_or_none()
            if tenant:
                suggested_tenant = {
                    "id": str(tenant.id),
                    "name": tenant.name,
                    "onmicrosoft_domain": tenant.onmicrosoft_domain,
                    "admin_email": tenant.admin_email,
                    "current_domain_id": str(tenant.domain_id) if tenant.domain_id else None,
                    "current_custom_domain": tenant.custom_domain,
                }
        
        orphaned_list.append({
            "domain_id": str(d.id),
            "domain_name": d.name,
            "status": d.status.value,
            "error_message": d.error_message,
            "extracted_tenant_name": tenant_name,
            "suggested_tenant": suggested_tenant,
            "cloudflare_zone_id": d.cloudflare_zone_id,
            "type": "orphaned_by_bug"
        })
    
    problem_list = []
    for d in problem_domains:
        tenant_info = None
        if d.tenant:
            tenant_info = {
                "id": str(d.tenant.id),
                "name": d.tenant.name,
                "onmicrosoft_domain": d.tenant.onmicrosoft_domain,
                "admin_email": d.tenant.admin_email,
            }
        problem_list.append({
            "domain_id": str(d.id),
            "domain_name": d.name,
            "status": d.status.value,
            "error_message": d.error_message,
            "tenant": tenant_info,
            "tenant_link_preserved": d.tenant_id is not None,
            "type": "m365_removal_failed"
        })
    
    return {
        "orphaned_domains": orphaned_list,
        "orphaned_count": len(orphaned_list),
        "problem_domains": problem_list,
        "problem_count": len(problem_list),
        "total_needing_attention": len(orphaned_list) + len(problem_list),
        "note": (
            "Orphaned domains had their tenant links incorrectly cleared by the old bug. "
            "Use POST /repair-links to re-link them. "
            "Problem domains still have their tenant links — just retry removal."
        )
    }


class RepairLinkEntry(BaseModel):
    domain_name: str
    tenant_onmicrosoft_domain: Optional[str] = None  # Look up tenant by onmicrosoft domain
    tenant_name: Optional[str] = None  # Or look up by tenant name


class RepairLinksRequest(BaseModel):
    links: List[RepairLinkEntry]


@router.post("/repair-links")
async def repair_domain_tenant_links(
    request: RepairLinksRequest,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Re-link domains that were incorrectly unlinked from their tenants.
    
    For each entry, provide either tenant_onmicrosoft_domain or tenant_name
    to identify which tenant to re-link the domain to.
    
    This restores the domain→tenant and tenant→domain relationships and sets
    the domain status to TENANT_LINKED so it can re-enter the removal flow.
    """
    if not request.links:
        raise HTTPException(status_code=400, detail="No links provided")
    
    results = []
    repaired = 0
    failed = 0
    
    for entry in request.links:
        domain_name = entry.domain_name.strip().lower()
        repair_result = {
            "domain": domain_name,
            "success": False,
            "error": None
        }
        
        # Find the domain
        d_result = await db.execute(
            select(Domain).where(Domain.name == domain_name)
        )
        domain = d_result.scalar_one_or_none()
        
        if not domain:
            repair_result["error"] = f"Domain '{domain_name}' not found in database"
            failed += 1
            results.append(repair_result)
            continue
        
        # Find the tenant
        tenant = None
        if entry.tenant_onmicrosoft_domain:
            t_result = await db.execute(
                select(Tenant).where(
                    Tenant.onmicrosoft_domain == entry.tenant_onmicrosoft_domain.strip()
                )
            )
            tenant = t_result.scalar_one_or_none()
        
        if not tenant and entry.tenant_name:
            t_result = await db.execute(
                select(Tenant).where(Tenant.name == entry.tenant_name.strip())
            )
            tenant = t_result.scalar_one_or_none()
        
        if not tenant:
            # Last resort: try to extract from the domain's error_message
            if domain.error_message:
                match = re.search(r"Removed from tenant '([^']+)'", domain.error_message)
                if match:
                    t_result = await db.execute(
                        select(Tenant).where(Tenant.name == match.group(1))
                    )
                    tenant = t_result.scalar_one_or_none()
        
        if not tenant:
            repair_result["error"] = (
                f"Could not find tenant. Provide tenant_onmicrosoft_domain or tenant_name. "
                f"Domain error_message: {domain.error_message}"
            )
            failed += 1
            results.append(repair_result)
            continue
        
        # Re-link domain ↔ tenant
        try:
            domain.tenant_id = tenant.id
            domain.status = DomainStatus.TENANT_LINKED
            domain.error_message = (
                f"Re-linked to tenant '{tenant.name}' via repair at {datetime.utcnow().isoformat()} "
                f"(previous: {domain.error_message})"
            )
            
            # Also re-link tenant → domain if it's not already linked to another domain
            if not tenant.domain_id:
                tenant.domain_id = domain.id
                tenant.custom_domain = domain.name
            
            await db.commit()
            
            repair_result["success"] = True
            repair_result["tenant_name"] = tenant.name
            repair_result["tenant_onmicrosoft"] = tenant.onmicrosoft_domain
            repair_result["new_status"] = DomainStatus.TENANT_LINKED.value
            repaired += 1
        except Exception as e:
            await db.rollback()
            repair_result["error"] = f"Database error: {e}"
            failed += 1
        
        results.append(repair_result)
    
    return {
        "total": len(request.links),
        "repaired": repaired,
        "failed": failed,
        "results": results
    }
