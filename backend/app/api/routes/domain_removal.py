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
"""
import asyncio
import io
import uuid as uuid_mod
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session, async_engine, SessionLocal
from app.services.domain_removal_service import domain_removal_service

router = APIRouter(prefix="/api/v1/domain-removal", tags=["domain-removal"])


# ===== Request/Response Models =====

class DBRemovalRequest(BaseModel):
    domains: List[str]
    skip_m365: bool = False
    headless: bool = False
    stagger_seconds: int = 10


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
                        headless=request.headless
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
