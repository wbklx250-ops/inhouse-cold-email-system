"""
Domain Checker API routes.

Provides endpoints to:
1. Upload a CSV of tenants and check their domains
2. Check domains for tenants in an existing batch
3. Poll job progress
4. Download results as CSV
"""

from __future__ import annotations

import csv
import io
import uuid
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.session import SessionLocal
from app.models.tenant import Tenant
from app.services.selenium.domain_checker import (
    check_tenants_parallel,
    TenantCheckResult,
    CHECKER_PARALLEL_BROWSERS,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/domain-checker", tags=["domain-checker"])

# In-memory job storage (same pattern as existing step4_jobs, step8_jobs in wizard.py)
checker_jobs: dict[str, dict] = {}


class CheckerJobStatus(BaseModel):
    job_id: str
    status: str  # "running", "complete", "error"
    total: int
    processed: int
    results: list[dict] = []
    summary: dict = {}
    started_at: str = ""
    completed_at: Optional[str] = None


# === ENDPOINTS ===


@router.post("/check-csv")
async def check_from_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    totp_secret: Optional[str] = Form(None),  # Shared TOTP if all tenants use the same
    headless: bool = Form(True),
    max_workers: int = Form(3),
):
    """
    Upload a CSV of tenants and check which domains are set up.

    CSV must have columns matching (case-insensitive, flexible):
    - Email/Username/Admin column containing admin@xxx.onmicrosoft.com
    - Password column
    - Optional: TOTP Secret column

    Returns a job_id to poll for progress.
    """
    # Parse CSV
    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    tenants = []
    for row in reader:
        email = None
        password = None
        row_totp = None

        for k, v in row.items():
            kl = k.strip().lower()
            if any(x in kl for x in ["email", "user name", "username", "admin"]):
                if v and "@" in v.strip():
                    email = v.strip()
            if any(x in kl for x in ["password", "pass", "pwd"]):
                if v:
                    password = v.strip()
            if any(x in kl for x in ["totp", "mfa", "secret"]):
                if v:
                    row_totp = v.strip()

        if email and password:
            tenants.append({
                "admin_email": email,
                "admin_password": password,
                "totp_secret": row_totp or totp_secret,  # Row-level overrides shared
            })

    if not tenants:
        raise HTTPException(400, "No valid tenants found in CSV. Need email + password columns.")

    # Clamp max_workers to safe range
    max_workers = max(1, min(max_workers, 10))

    # Create job
    job_id = str(uuid.uuid4())
    checker_jobs[job_id] = {
        "status": "running",
        "total": len(tenants),
        "processed": 0,
        "results": [],
        "started_at": datetime.utcnow().isoformat(),
        "completed_at": None,
    }

    # Run in background
    background_tasks.add_task(_run_checker_job, job_id, tenants, headless, max_workers)

    return {"job_id": job_id, "total_tenants": len(tenants)}


@router.post("/check-batch/{batch_id}")
async def check_from_batch(
    batch_id: UUID,
    background_tasks: BackgroundTasks,
    headless: bool = Form(True),
    max_workers: int = Form(3),
    db: AsyncSession = Depends(get_db),
):
    """
    Check domains for all tenants in an existing batch.
    Uses stored credentials and TOTP secrets from the database.
    """
    result = await db.execute(
        select(Tenant).where(Tenant.batch_id == batch_id)
    )
    tenants_db = result.scalars().all()

    if not tenants_db:
        raise HTTPException(404, f"No tenants found in batch {batch_id}")

    tenants = []
    for t in tenants_db:
        tenants.append({
            "admin_email": t.admin_email,
            "admin_password": t.admin_password,
            "totp_secret": t.totp_secret,
        })

    job_id = str(uuid.uuid4())
    checker_jobs[job_id] = {
        "status": "running",
        "total": len(tenants),
        "processed": 0,
        "results": [],
        "started_at": datetime.utcnow().isoformat(),
        "completed_at": None,
    }

    # Clamp max_workers to safe range
    max_workers = max(1, min(max_workers, 10))

    background_tasks.add_task(_run_checker_job, job_id, tenants, headless, max_workers)

    return {"job_id": job_id, "total_tenants": len(tenants)}


@router.get("/jobs/{job_id}", response_model=CheckerJobStatus)
async def get_job_status(job_id: str):
    """Poll job progress."""
    job = checker_jobs.get(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")

    # Build summary
    results = job["results"]
    summary = {}
    if results:
        auth_ok = sum(1 for r in results if r.get("login_success"))
        auth_fail = len(results) - auth_ok
        has_verified = sum(1 for r in results if r.get("login_success") and r.get("verified_count", 0) > 0)
        has_unverified = sum(1 for r in results if r.get("login_success") and r.get("unverified_count", 0) > 0)
        no_domains = sum(1 for r in results if r.get("login_success") and r.get("custom_domain_count", 0) == 0)
        total_verified = sum(r.get("verified_count", 0) for r in results)
        total_unverified = sum(r.get("unverified_count", 0) for r in results)

        summary = {
            "auth_success": auth_ok,
            "auth_failed": auth_fail,
            "tenants_with_verified_domains": has_verified,
            "tenants_with_unverified_domains": has_unverified,
            "tenants_no_domains": no_domains,
            "total_verified_domains": total_verified,
            "total_unverified_domains": total_unverified,
        }

    return CheckerJobStatus(
        job_id=job_id,
        status=job["status"],
        total=job["total"],
        processed=job["processed"],
        results=results,
        summary=summary,
        started_at=job["started_at"],
        completed_at=job.get("completed_at"),
    )


@router.get("/jobs/{job_id}/csv")
async def download_results_csv(job_id: str):
    """Download results as CSV."""
    job = checker_jobs.get(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    if job["status"] != "complete":
        raise HTTPException(400, "Job not yet complete")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Tenant", "Admin Email", "Login Success", "Login Error",
        "Verified Domain Count", "Unverified Domain Count",
        "Verified Domains", "Unverified Domains",
    ])

    for r in job["results"]:
        verified_names = "; ".join(d["name"] for d in r.get("verified_domains", []))
        unverified_names = "; ".join(d["name"] for d in r.get("unverified_domains", []))

        writer.writerow([
            r.get("tenant_name", ""),
            r.get("admin_email", ""),
            r.get("login_success", False),
            r.get("login_error", ""),
            r.get("verified_count", 0),
            r.get("unverified_count", 0),
            verified_names,
            unverified_names,
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=domain_check_{job_id[:8]}.csv"
        },
    )


# === BACKGROUND TASK ===


async def _enrich_totp_from_db(tenants: list[dict]) -> None:
    """
    For tenants missing a TOTP secret, try to look it up from the database.
    This allows CSV uploads (which often lack TOTP columns) to still work
    if the tenants already exist in the DB with stored TOTP secrets.
    """
    emails_needing_totp = [t["admin_email"] for t in tenants if not t.get("totp_secret")]
    if not emails_needing_totp:
        return

    logger.info(f"Looking up TOTP secrets from DB for {len(emails_needing_totp)} tenants...")
    try:
        async with SessionLocal() as db:
            result = await db.execute(
                select(Tenant.admin_email, Tenant.totp_secret).where(
                    Tenant.admin_email.in_(emails_needing_totp),
                    Tenant.totp_secret.isnot(None),
                )
            )
            db_secrets = {row.admin_email: row.totp_secret for row in result}

        enriched = 0
        for tenant in tenants:
            if not tenant.get("totp_secret") and tenant["admin_email"] in db_secrets:
                tenant["totp_secret"] = db_secrets[tenant["admin_email"]]
                enriched += 1

        if enriched:
            logger.info(f"Enriched {enriched} tenants with TOTP secrets from database")
    except Exception as e:
        logger.warning(f"Could not look up TOTP secrets from DB: {e}")


async def _run_checker_job(job_id: str, tenants: list[dict], headless: bool, max_workers: int = 3):
    """
    Process tenants with chunked parallel processing.
    Uses max_workers for concurrency (user-selected, default: 3).
    """
    job = checker_jobs[job_id]
    total = job["total"]

    # Enrich missing TOTP secrets from database (for CSV uploads)
    await _enrich_totp_from_db(tenants)

    def on_progress(processed, total, latest_result):
        """Update job state as each tenant completes."""
        job["processed"] = processed
        if latest_result:
            job["results"].append(
                latest_result.to_dict() if hasattr(latest_result, 'to_dict') else latest_result
            )

    try:
        logger.info(f"[Job {job_id[:8]}] Starting parallel check: {total} tenants, {max_workers} workers")

        results = await check_tenants_parallel(
            tenants=tenants,
            headless=headless,
            max_workers=max_workers,
            progress_callback=on_progress,
        )

        # Ensure all results are in job (callback may have missed some on exceptions)
        job["results"] = [r.to_dict() if hasattr(r, 'to_dict') else r for r in results]
        job["processed"] = len(results)
        job["status"] = "complete"
        job["completed_at"] = datetime.utcnow().isoformat()

        # Log summary
        auth_ok = sum(1 for r in results if (r.login_success if hasattr(r, 'login_success') else r.get('login_success')))
        logger.info(f"[Job {job_id[:8]}] Complete — {auth_ok}/{total} auth success")

    except Exception as e:
        logger.error(f"[Job {job_id[:8]}] Job failed: {e}")
        job["status"] = "error"
        job["completed_at"] = datetime.utcnow().isoformat()
