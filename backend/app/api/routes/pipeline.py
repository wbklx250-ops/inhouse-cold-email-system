"""
Pipeline API — Collect-everything-upfront, then execute automatically.
"""
import asyncio
import logging
import os
import random
import time
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update

from app.db.session import get_db_session as get_db, SessionLocal
from app.models.batch import SetupBatch, BatchStatus
from app.models.domain import Domain, DomainStatus
from app.models.tenant import Tenant, TenantStatus
from app.models.mailbox import Mailbox
from app.models.pipeline_log import PipelineLog
from app.services.validation_service import (
    parse_domains_csv_content,
    parse_tenants_csv_content,
    parse_credentials_txt_content,
    cross_validate,
)
from app.services.tenant_import import tenant_import_service
from app.services.cloudflare import cloudflare_service
from app.services.selenium.admin_portal import enable_org_smtp_auth

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])
logger = logging.getLogger(__name__)

# In-memory pipeline job tracking
pipeline_jobs = {}

MAX_PIPELINE_RETRIES = 4   # Max retries per tenant per step
STEP5_MAX_WORKERS = 2      # Max parallel browsers for first login (Railway memory limit)

STEP_NAMES = {
    1: "Create Cloudflare Zones",
    2: "Update Nameservers",
    3: "Verify NS Propagation",
    4: "Create DNS Records & Redirects",
    5: "First Login Automation",
    6: "M365 Domain Setup & DKIM",
    7: "Create Mailboxes & Delegate",
    8: "Enable SMTP Auth",
    9: "Export Credentials",
    10: "Upload to Sequencer",
}


@router.post("/validate")
async def validate_inputs(
    domains_csv: UploadFile = File(...),
    tenants_csv: UploadFile = File(...),
    credentials_txt: UploadFile = File(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
):
    """
    Validate all input files without creating anything.
    Returns preview counts and any errors/warnings.
    Call this on file upload for instant feedback.
    """
    domains_content = (await domains_csv.read()).decode("utf-8-sig")
    tenants_content = (await tenants_csv.read()).decode("utf-8-sig")
    creds_content = (await credentials_txt.read()).decode("utf-8-sig")

    domains, domain_errors = parse_domains_csv_content(domains_content)
    tenants, tenant_errors = parse_tenants_csv_content(tenants_content)
    credentials, cred_errors = parse_credentials_txt_content(creds_content)

    # If parsing failed, return errors immediately
    all_parse_errors = domain_errors + tenant_errors + cred_errors
    if all_parse_errors:
        return {
            "valid": False,
            "errors": all_parse_errors,
            "warnings": [],
            "summary": {
                "domains_count": len(domains),
                "tenants_count": len(tenants),
                "credentials_matched": 0,
            }
        }

    # Cross-validate (mailboxes_per_tenant always 50)
    result = cross_validate(domains, tenants, credentials, first_name, last_name, 50)
    return result


@router.post("/create-and-start")
async def create_and_start(
    batch_name: str = Form(...),
    domains_csv: UploadFile = File(...),
    tenants_csv: UploadFile = File(...),
    credentials_txt: UploadFile = File(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    sequencer_platform: str = Form(""),
    sequencer_account_id: str = Form(""),
    sequencer_api_key: str = Form(""),
    profile_photo: UploadFile = File(None),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
):
    """
    Create batch with all data and start the automated pipeline.

    This is the MAIN entry point. It:
    1. Validates all inputs
    2. Creates the batch
    3. Imports domains
    4. Imports tenants + credentials
    5. Links domains to tenants (1:1 in order)
    6. Saves all configuration
    7. Starts the pipeline in background
    8. Returns batch_id for progress tracking
    """
    # Read file contents
    domains_content = (await domains_csv.read()).decode("utf-8-sig")
    tenants_content = (await tenants_csv.read()).decode("utf-8-sig")
    creds_content = (await credentials_txt.read()).decode("utf-8-sig")

    # Parse and validate
    domains, domain_errors = parse_domains_csv_content(domains_content)
    tenants, tenant_errors = parse_tenants_csv_content(tenants_content)
    credentials, cred_errors = parse_credentials_txt_content(creds_content)

    all_errors = domain_errors + tenant_errors + cred_errors
    if all_errors:
        raise HTTPException(400, detail={"errors": all_errors})

    validation = cross_validate(domains, tenants, credentials, first_name, last_name, 50)
    if not validation["valid"]:
        raise HTTPException(400, detail={"errors": validation["errors"]})

    # Save profile photo if provided
    photo_path = None
    if profile_photo and profile_photo.filename:
        photo_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "uploads", "batch_photos")
        os.makedirs(photo_dir, exist_ok=True)
        photo_path = os.path.join(photo_dir, f"{batch_name}_{profile_photo.filename}")
        with open(photo_path, "wb") as f:
            f.write(await profile_photo.read())

    # Create batch
    batch = SetupBatch(
        name=batch_name,
        status=BatchStatus.IN_PROGRESS,
        current_step=1,
        new_admin_password="#Sendemails1",  # Always hardcoded
        persona_first_name=first_name,
        persona_last_name=last_name,
        mailboxes_per_tenant=50,  # Always 50
        sequencer_platform=sequencer_platform or None,
        sequencer_login_email=None,  # No longer collected here
        sequencer_login_password=None,  # No longer collected here
        profile_photo_path=photo_path,
        pipeline_status="running",
        pipeline_step=1,
        pipeline_step_name=STEP_NAMES[1],
        pipeline_started_at=datetime.utcnow(),
        total_domains=len(domains),
        total_tenants=len(tenants),
    )
    db.add(batch)
    await db.flush()  # Get batch.id

    batch_id = batch.id

    # Import domains — handle duplicates by reusing existing domain records
    imported_domain_count = 0
    for d in domains:
        parts = d["name"].rsplit(".", 1)
        tld = parts[-1] if len(parts) > 1 else ""

        # Check if domain already exists
        existing = (await db.execute(
            select(Domain).where(Domain.name == d["name"])
        )).scalar_one_or_none()

        if existing:
            # Re-assign to this batch (domain may have been in a deleted/old batch)
            existing.batch_id = batch_id
            existing.redirect_url = d.get("redirect_url", "") or existing.redirect_url
            existing.status = DomainStatus.PURCHASED
            existing.cloudflare_zone_status = existing.cloudflare_zone_status or "pending"
            imported_domain_count += 1
        else:
            domain = Domain(
                batch_id=batch_id,
                name=d["name"],
                tld=tld,
                redirect_url=d.get("redirect_url", ""),
                status=DomainStatus.PURCHASED,
                cloudflare_zone_status="pending",
                cloudflare_nameservers=[],
            )
            db.add(domain)
            imported_domain_count += 1

    await db.flush()

    # Import tenants with credentials using the existing service
    result = await tenant_import_service.import_tenants(
        db, batch_id, tenants_content, creds_content, provider="reseller"
    )

    # Auto-link domains to tenants (1:1 in order)
    link_result = await tenant_import_service.auto_link_domains(db, batch_id)

    await db.commit()

    # Initialize pipeline job tracking
    job_id = str(batch_id)
    pipeline_jobs[job_id] = {
        "status": "running",
        "batch_id": job_id,
        "batch_name": batch_name,
        "started_at": datetime.utcnow().isoformat(),
        "current_step": 1,
        "current_step_name": STEP_NAMES[1],
        "message": "Starting pipeline...",
        "total_domains": len(domains),
        "total_tenants": validation["summary"]["credentials_matched"],
        "steps": {str(i): {"status": "pending", "completed": 0, "failed": 0, "total": 0} for i in range(1, 11)},
        "errors": [],
        "activity_log": [],
    }

    # Start pipeline in background
    background_tasks.add_task(run_pipeline, batch_id)

    return {
        "success": True,
        "batch_id": str(batch_id),
        "batch_name": batch_name,
        "domains_imported": imported_domain_count,
        "tenants_imported": result.get("imported", 0),
        "tenants_linked": link_result.get("linked", 0),
        "pipeline_started": True,
        "warnings": validation.get("warnings", []),
    }


@router.get("/{batch_id}/status")
async def get_pipeline_status(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get real-time pipeline status for the progress dashboard."""
    job_id = str(batch_id)

    if job_id in pipeline_jobs:
        return pipeline_jobs[job_id]

    # Fallback: read from database
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")

    return {
        "status": batch.pipeline_status or "unknown",
        "batch_id": str(batch_id),
        "batch_name": batch.name,
        "current_step": batch.pipeline_step or 0,
        "current_step_name": STEP_NAMES.get(batch.pipeline_step, "Unknown"),
        "total_domains": batch.total_domains or 0,
        "total_tenants": batch.total_tenants or 0,
    }


@router.post("/{batch_id}/confirm-nameservers")
async def confirm_nameservers(
    batch_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """User confirms they've updated nameservers at Porkbun. Resumes pipeline."""
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")

    batch.ns_confirmed_at = datetime.utcnow()
    await db.commit()

    job_id = str(batch_id)

    # Check if background task is still alive
    task_alive = (job_id in pipeline_jobs and
                  pipeline_jobs[job_id].get("status") == "running")

    if task_alive:
        # Task is alive and polling — just set the flag
        pipeline_jobs[job_id]["ns_confirmed"] = True
        pipeline_jobs[job_id]["message"] = "Nameservers confirmed — checking propagation..."
        logger.info(f"NS confirmed for {batch_id} — pipeline task is alive, will pick up flag")
    else:
        # Task is DEAD — re-launch pipeline from Step 3 (NS propagation)
        logger.warning(f"NS confirmed for {batch_id} but pipeline task is DEAD — re-launching from Step 3")
        pipeline_jobs.pop(job_id, None)  # Clear stale state
        batch.pipeline_status = "running"
        await db.commit()
        background_tasks.add_task(run_pipeline, batch_id, 3)  # Skip Steps 1-2

    return {"success": True, "message": "Nameservers confirmed. Pipeline resuming."}


@router.post("/{batch_id}/retry-failed")
async def retry_failed(
    batch_id: UUID,
    step: int = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
):
    """Retry failed items from a specific step or current step."""
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")

    # Reset retry counts for the target step(s) using bulk update
    from sqlalchemy import update as sql_update

    if step == 5 or step is None:
        await db.execute(
            sql_update(Tenant).where(
                Tenant.batch_id == batch_id,
                Tenant.first_login_completed != True,
            ).values(step4_retry_count=0, setup_error=None)
        )
    if step == 6 or step is None:
        await db.execute(
            sql_update(Tenant).where(
                Tenant.batch_id == batch_id,
                Tenant.domain_verified_in_m365 != True,
            ).values(step5_retry_count=0, setup_error=None)
        )
    if step == 7 or step is None:
        await db.execute(
            sql_update(Tenant).where(
                Tenant.batch_id == batch_id,
                Tenant.step6_complete != True,
            ).values(step6_retry_count=0, step6_error=None)
        )
    if step == 8 or step is None:
        await db.execute(
            sql_update(Tenant).where(
                Tenant.batch_id == batch_id,
                Tenant.step7_complete != True,
            ).values(step7_retry_count=0, step7_error=None)
        )

    # Determine start step
    start_step = step or batch.pipeline_step or 1

    batch.pipeline_status = "running"
    await db.commit()

    job_id = str(batch_id)
    pipeline_jobs.pop(job_id, None)  # Clear stale state

    background_tasks.add_task(run_pipeline, batch_id, start_step)

    return {
        "success": True,
        "message": f"Retrying from step {start_step} ({STEP_NAMES.get(start_step, 'Unknown')})",
    }


@router.post("/{batch_id}/pause")
async def pause_pipeline(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """Pause the pipeline. In-progress operations will complete."""
    job_id = str(batch_id)
    if job_id in pipeline_jobs:
        pipeline_jobs[job_id]["status"] = "paused"
        pipeline_jobs[job_id]["message"] = "Pipeline paused by user"

    batch = await db.get(SetupBatch, batch_id)
    if batch:
        batch.pipeline_status = "paused"
        batch.pipeline_paused_at = datetime.utcnow()
        await db.commit()

    return {"success": True}


@router.post("/{batch_id}/resume")
async def resume_pipeline(
    batch_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Resume a paused/crashed pipeline from where it left off."""
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")

    # Determine which step to resume from
    resume_step = batch.pipeline_step or 1

    # If we were on Step 2 (NS wait) and NS is already confirmed, skip to 3
    if resume_step == 2 and batch.ns_confirmed_at:
        resume_step = 3

    batch.pipeline_status = "running"
    batch.pipeline_paused_at = None
    await db.commit()

    job_id = str(batch_id)
    pipeline_jobs.pop(job_id, None)  # Clear stale in-memory state

    logger.info(f"Resuming pipeline for batch {batch_id} from step {resume_step}")
    background_tasks.add_task(run_pipeline, batch_id, resume_step)

    return {
        "success": True,
        "message": f"Pipeline resumed from step {resume_step} ({STEP_NAMES.get(resume_step, 'Unknown')})",
    }


@router.get("/{batch_id}/activity-log")
async def get_activity_log(batch_id: UUID, limit: int = 50, db: AsyncSession = Depends(get_db)):
    """Get recent activity log entries."""
    result = await db.execute(
        select(PipelineLog)
        .where(PipelineLog.batch_id == batch_id)
        .order_by(PipelineLog.created_at.desc())
        .limit(limit)
    )
    logs = result.scalars().all()

    return {
        "logs": [
            {
                "step": log.step,
                "step_name": log.step_name,
                "item_type": log.item_type,
                "item_name": log.item_name,
                "status": log.status,
                "message": log.message,
                "error": log.error_detail,
                "timestamp": log.created_at.isoformat(),
            }
            for log in logs
        ]
    }


@router.get("/{batch_id}/credentials-export")
async def export_credentials(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """Export all mailbox credentials as CSV."""
    import io
    import csv

    result = await db.execute(
        select(Mailbox).where(Mailbox.batch_id == batch_id)
    )
    mailboxes = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["DisplayName", "EmailAddress", "Password", "Domain", "TenantName"])

    for mb in mailboxes:
        # Get tenant for domain info
        tenant = await db.get(Tenant, mb.tenant_id)
        writer.writerow([
            mb.display_name,
            mb.email,
            mb.password,
            tenant.custom_domain if tenant else "",
            tenant.name if tenant else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=credentials_batch_{batch_id}.csv"}
    )


async def _update_pipeline(batch_id: UUID, step: int, status: str, message: str):
    """Update both in-memory job tracker and database."""
    job_id = str(batch_id)

    if job_id in pipeline_jobs:
        pipeline_jobs[job_id]["current_step"] = step
        pipeline_jobs[job_id]["current_step_name"] = STEP_NAMES.get(step, "Unknown")
        pipeline_jobs[job_id]["status"] = status
        pipeline_jobs[job_id]["message"] = message

    try:
        async with SessionLocal() as db:
            batch = await db.get(SetupBatch, batch_id)
            if batch:
                batch.pipeline_step = step
                batch.pipeline_step_name = STEP_NAMES.get(step, "Unknown")
                batch.pipeline_status = status
                await db.commit()
    except Exception as e:
        logger.error(f"Failed to update pipeline status in DB: {e}")


async def _check_paused_or_stopped(batch_id: UUID) -> bool:
    """Check if pipeline was paused or stopped by user."""
    job_id = str(batch_id)
    if job_id in pipeline_jobs:
        return pipeline_jobs[job_id].get("status") in ("paused", "stopped")
    return False


async def run_pipeline(batch_id: UUID, start_from_step: int = 1):
    """
    MAIN PIPELINE ORCHESTRATOR.

    Runs Steps 1-10 sequentially, pausing only at Step 2 (NS update).
    Each step calls existing service functions.
    Errors on individual items don't block the pipeline — they're logged and the item is skipped.
    Supports resuming from any step via start_from_step parameter.
    """
    job_id = str(batch_id)
    logger.info(f"🚀 Pipeline started for batch {batch_id} from step {start_from_step}")

    # Initialize in-memory job tracker if not exists
    if job_id not in pipeline_jobs:
        async with SessionLocal() as db:
            batch = await db.get(SetupBatch, batch_id)
            if not batch:
                logger.error(f"Batch {batch_id} not found")
                return
            pipeline_jobs[job_id] = {
                "status": "running",
                "batch_id": job_id,
                "batch_name": batch.name or "",
                "started_at": datetime.utcnow().isoformat(),
                "current_step": start_from_step,
                "current_step_name": STEP_NAMES.get(start_from_step, "Unknown"),
                "message": f"Resuming from step {start_from_step}...",
                "total_domains": batch.total_domains or 0,
                "total_tenants": batch.total_tenants or 0,
                "steps": {str(i): {"status": "pending", "completed": 0, "failed": 0, "total": 0} for i in range(1, 11)},
                "errors": [],
                "activity_log": [],
            }

    pipeline_jobs[job_id]["status"] = "running"

    try:
        # Reset retry counts only for fresh pipeline runs (step 1)
        if start_from_step <= 1:
            async with SessionLocal() as db:
                await db.execute(
                    update(Tenant).where(Tenant.batch_id == batch_id).values(
                        step4_retry_count=0,
                        step5_retry_count=0,
                        step6_retry_count=0,
                        step7_retry_count=0,
                    )
                )
                await db.commit()
            logger.info(f"Reset retry counts for batch {batch_id}")

        # ================================================================
        # STEP 1: Create Cloudflare Zones
        # ================================================================
        if start_from_step <= 1:
          try:
            await _update_pipeline(batch_id, 1, "running", "Creating Cloudflare zones...")
            await log_activity(batch_id, 1, STEP_NAMES[1], status="started", message="Starting zone creation")

            async with SessionLocal() as db:
                domains = (await db.execute(
                    select(Domain).where(
                        Domain.batch_id == batch_id,
                        Domain.cloudflare_zone_id == None,  # No zone yet
                    )
                )).scalars().all()

                zones_created = 0
                zones_failed = 0
                ns_groups = {}

                for domain in domains:
                    if await _check_paused_or_stopped(batch_id):
                        await _update_pipeline(batch_id, 1, "paused", "Paused by user")
                        return

                    try:
                        zone_result = await cloudflare_service.create_zone(domain.name)
                        if zone_result.get("zone_id"):
                            domain.cloudflare_zone_id = zone_result["zone_id"]
                            domain.cloudflare_nameservers = zone_result.get("nameservers", [])
                            domain.status = DomainStatus.CF_ZONE_ACTIVE
                            zones_created += 1

                            # Phase 1 DNS: CNAME proxy + DMARC (before NS propagation)
                            try:
                                await cloudflare_service.create_phase1_dns(zone_result["zone_id"], domain.name)
                                domain.phase1_cname_added = True
                                domain.phase1_dmarc_added = True
                            except Exception as dns_e:
                                if "already exists" in str(dns_e).lower():
                                    logger.info(f"Phase 1 DNS already exists for {domain.name} — skipping")
                                    domain.phase1_cname_added = True
                                    domain.phase1_dmarc_added = True
                                else:
                                    logger.warning(f"Phase 1 DNS failed for {domain.name}: {dns_e}")

                            # Track NS groups
                            ns_key = ",".join(sorted(domain.cloudflare_nameservers or []))
                            if ns_key not in ns_groups:
                                ns_groups[ns_key] = []
                            ns_groups[ns_key].append(domain.name)

                            await log_activity(batch_id, 1, STEP_NAMES[1], "domain", str(domain.id), domain.name, "completed", "Zone created")
                        else:
                            zones_failed += 1
                            domain.error_message = zone_result.get("error", "Zone creation failed")
                            await log_activity(batch_id, 1, STEP_NAMES[1], "domain", str(domain.id), domain.name, "failed", domain.error_message)

                    except Exception as e:
                        zones_failed += 1
                        domain.error_message = str(e)
                        await log_activity(batch_id, 1, STEP_NAMES[1], "domain", str(domain.id), domain.name, "failed", str(e))

                    await db.commit()

                # Update batch counters — count ALL domains with zones (including re-used)
                total_with_zones = await db.scalar(
                    select(func.count(Domain.id)).where(
                        Domain.batch_id == batch_id,
                        Domain.cloudflare_zone_id.isnot(None),
                    )
                ) or 0
                batch = await db.get(SetupBatch, batch_id)
                if batch:
                    batch.zones_completed = total_with_zones
                    await db.commit()

            # Handle re-used domains that already have zone_id but no Phase 1 DNS flags
            async with SessionLocal() as db:
                reused_domains = (await db.execute(
                    select(Domain).where(
                        Domain.batch_id == batch_id,
                        Domain.cloudflare_zone_id.isnot(None),
                        Domain.phase1_cname_added != True,
                    )
                )).scalars().all()

                for domain in reused_domains:
                    try:
                        await cloudflare_service.create_phase1_dns(domain.cloudflare_zone_id, domain.name)
                        domain.phase1_cname_added = True
                        domain.phase1_dmarc_added = True
                    except Exception as e:
                        if "already exists" in str(e).lower():
                            domain.phase1_cname_added = True
                            domain.phase1_dmarc_added = True
                        else:
                            logger.warning(f"Phase 1 DNS for re-used domain {domain.name}: {e}")
                    await db.commit()

            # Store NS groups in job for frontend display
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["nameserver_groups"] = [
                    {"nameservers": ns.split(","), "domains": doms, "count": len(doms)}
                    for ns, doms in ns_groups.items()
                ]
                pipeline_jobs[job_id]["steps"]["1"]["status"] = "completed"
                pipeline_jobs[job_id]["steps"]["1"]["completed"] = total_with_zones
                pipeline_jobs[job_id]["steps"]["1"]["failed"] = zones_failed

            logger.info(f"Step 1: {zones_created} new zones created, {total_with_zones} total zones ready")

          except Exception as step_error:
            logger.error(f"Step 1 CRASHED (continuing to next step): {step_error}")
            import traceback
            logger.error(traceback.format_exc())
            await log_activity(batch_id, 1, STEP_NAMES[1], status="error", message=str(step_error))
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["1"]["status"] = "error"
                pipeline_jobs[job_id]["errors"].append({"step": 1, "error": str(step_error)})
        else:
            logger.info(f"Skipping Step 1 (starting from step {start_from_step})")
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["1"]["status"] = "completed"

        # ================================================================
        # STEP 2-3: NS Update + Propagation (auto-skip if already done)
        # ================================================================
        if start_from_step <= 2:
          try:
            # Check if NS already confirmed (re-used domains)
            async with SessionLocal() as db:
                already_propagated = await db.scalar(
                    select(func.count(Domain.id)).where(
                        Domain.batch_id == batch_id,
                        Domain.ns_propagated_at.isnot(None),
                    )
                ) or 0
                total_domains = await db.scalar(
                    select(func.count(Domain.id)).where(Domain.batch_id == batch_id)
                ) or 0

            skip_ns_wait = (total_domains > 0 and already_propagated >= total_domains * 0.95)

            if skip_ns_wait:
                logger.info(f"Step 2-3: {already_propagated}/{total_domains} domains already have NS propagated — skipping NS wait")
                if job_id in pipeline_jobs:
                    pipeline_jobs[job_id]["steps"]["2"]["status"] = "completed"
                    pipeline_jobs[job_id]["steps"]["3"]["status"] = "completed"
                    pipeline_jobs[job_id]["steps"]["3"]["completed"] = already_propagated
                    pipeline_jobs[job_id]["steps"]["3"]["total"] = total_domains
                await log_activity(batch_id, 2, STEP_NAMES[2], status="completed", message=f"Skipped — {already_propagated}/{total_domains} already propagated")
                await log_activity(batch_id, 3, STEP_NAMES[3], status="completed", message=f"Skipped — {already_propagated}/{total_domains} already propagated")
            else:
                # STEP 2: Pause for Nameserver Update (ONLY MANUAL STEP)
                await _update_pipeline(batch_id, 2, "paused", "Waiting for nameserver update confirmation...")
                await log_activity(batch_id, 2, STEP_NAMES[2], status="started", message="Waiting for user to update nameservers at Porkbun")

                if job_id in pipeline_jobs:
                    pipeline_jobs[job_id]["steps"]["2"]["status"] = "waiting_for_user"

                # Poll for NS confirmation with timeout and heartbeat
                step2_start = datetime.utcnow()
                STEP2_MAX_WAIT = 3600 * 24  # 24 hours max wait for user to update NS

                while True:
                    if await _check_paused_or_stopped(batch_id):
                        return

                    elapsed = (datetime.utcnow() - step2_start).total_seconds()
                    if elapsed > STEP2_MAX_WAIT:
                        logger.error("Step 2: Timed out waiting for NS confirmation after 24 hours")
                        await log_activity(batch_id, 2, STEP_NAMES[2], status="error", message="Timed out waiting for NS confirmation")
                        break

                    # Check DB flag (survives container restarts)
                    async with SessionLocal() as db:
                        batch = await db.get(SetupBatch, batch_id)
                        if batch and batch.ns_confirmed_at:
                            logger.info("Step 2: NS confirmed via DB flag")
                            break

                    # Check in-memory flag (fast path)
                    if job_id in pipeline_jobs and pipeline_jobs[job_id].get("ns_confirmed"):
                        logger.info("Step 2: NS confirmed via in-memory flag")
                        break

                    # Update heartbeat so dashboard knows task is alive
                    if job_id in pipeline_jobs:
                        pipeline_jobs[job_id]["last_heartbeat"] = datetime.utcnow().isoformat()

                    await asyncio.sleep(5)

                await log_activity(batch_id, 2, STEP_NAMES[2], status="completed", message="Nameservers confirmed by user")
                if job_id in pipeline_jobs:
                    pipeline_jobs[job_id]["steps"]["2"]["status"] = "completed"

                # ================================================================
                # STEP 3: Verify NS Propagation
                # ================================================================
                await _update_pipeline(batch_id, 3, "running", "Checking nameserver propagation...")
                await log_activity(batch_id, 3, STEP_NAMES[3], status="started")

                total_zones = 0
                total_propagated = 0
                NS_PROPAGATION_TIMEOUT = 3600 * 4  # 4 hours max
                ns_start_time = time.time()

                while True:
                    if await _check_paused_or_stopped(batch_id):
                        return

                    if time.time() - ns_start_time > NS_PROPAGATION_TIMEOUT:
                        logger.error(f"Step 3: NS propagation timed out after 4 hours")
                        await log_activity(batch_id, 3, STEP_NAMES[3], status="warning",
                            message=f"Timed out — {total_propagated}/{total_zones} propagated. Proceeding anyway.")
                        break

                    async with SessionLocal() as db:
                        # Find domains with zones that haven't propagated yet
                        domains = (await db.execute(
                            select(Domain).where(
                                Domain.batch_id == batch_id,
                                Domain.cloudflare_zone_id != None,
                                Domain.ns_propagated_at == None,
                            )
                        )).scalars().all()

                        if not domains:
                            break  # All propagated

                        for domain in domains:
                            try:
                                zone_status = await cloudflare_service.get_zone_status(domain.cloudflare_zone_id)
                                if zone_status == "active":
                                    domain.status = DomainStatus.NS_PROPAGATED
                                    domain.ns_propagated_at = datetime.utcnow()
                                    domain.nameservers_updated = True
                                    await log_activity(batch_id, 3, STEP_NAMES[3], "domain", str(domain.id), domain.name, "completed", "NS propagated")
                            except Exception as e:
                                logger.warning(f"Propagation check failed for {domain.name}: {e}")

                        await db.commit()

                        total_zones = await db.scalar(
                            select(func.count(Domain.id)).where(Domain.batch_id == batch_id, Domain.cloudflare_zone_id != None)
                        ) or 0
                        total_propagated = await db.scalar(
                            select(func.count(Domain.id)).where(Domain.batch_id == batch_id, Domain.ns_propagated_at != None)
                        ) or 0

                        batch = await db.get(SetupBatch, batch_id)
                        if batch:
                            batch.ns_propagated_count = total_propagated
                            await db.commit()

                    if job_id in pipeline_jobs:
                        pipeline_jobs[job_id]["steps"]["3"]["completed"] = total_propagated
                        pipeline_jobs[job_id]["steps"]["3"]["total"] = total_zones
                        pipeline_jobs[job_id]["message"] = f"NS propagation: {total_propagated}/{total_zones}"

                    if total_zones and total_propagated and total_propagated >= total_zones * 0.95:
                        logger.info(f"Step 3: {total_propagated}/{total_zones} propagated (≥95%), proceeding")
                        break

                    await asyncio.sleep(30)

                if job_id in pipeline_jobs:
                    pipeline_jobs[job_id]["steps"]["3"]["status"] = "completed"
                await log_activity(batch_id, 3, STEP_NAMES[3], status="completed", message=f"{total_propagated}/{total_zones} propagated")

          except Exception as step_error:
            logger.error(f"Step 2-3 CRASHED (continuing to next step): {step_error}")
            import traceback
            logger.error(traceback.format_exc())
            await log_activity(batch_id, 2, STEP_NAMES[2], status="error", message=str(step_error))
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["2"]["status"] = "error"
                pipeline_jobs[job_id]["steps"]["3"]["status"] = "error"
                pipeline_jobs[job_id]["errors"].append({"step": 2, "error": str(step_error)})

        elif start_from_step <= 3:
            # Skipping step 2 but need step 3 (NS propagation check)
            logger.info(f"Skipping Step 2 (starting from step {start_from_step})")
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["2"]["status"] = "completed"
          
            try:
                await _update_pipeline(batch_id, 3, "running", "Checking nameserver propagation...")
                await log_activity(batch_id, 3, STEP_NAMES[3], status="started")

                total_zones = 0
                total_propagated = 0
                NS_PROPAGATION_TIMEOUT = 3600 * 4
                ns_start_time = time.time()

                while True:
                    if await _check_paused_or_stopped(batch_id):
                        return

                    if time.time() - ns_start_time > NS_PROPAGATION_TIMEOUT:
                        logger.error(f"Step 3: NS propagation timed out after 4 hours")
                        await log_activity(batch_id, 3, STEP_NAMES[3], status="warning",
                            message=f"Timed out — {total_propagated}/{total_zones} propagated. Proceeding anyway.")
                        break

                    async with SessionLocal() as db:
                        domains = (await db.execute(
                            select(Domain).where(
                                Domain.batch_id == batch_id,
                                Domain.cloudflare_zone_id != None,
                                Domain.ns_propagated_at == None,
                            )
                        )).scalars().all()

                        if not domains:
                            break

                        for domain in domains:
                            try:
                                zone_status = await cloudflare_service.get_zone_status(domain.cloudflare_zone_id)
                                if zone_status == "active":
                                    domain.status = DomainStatus.NS_PROPAGATED
                                    domain.ns_propagated_at = datetime.utcnow()
                                    domain.nameservers_updated = True
                                    await log_activity(batch_id, 3, STEP_NAMES[3], "domain", str(domain.id), domain.name, "completed", "NS propagated")
                            except Exception as e:
                                logger.warning(f"Propagation check failed for {domain.name}: {e}")

                        await db.commit()

                        total_zones = await db.scalar(
                            select(func.count(Domain.id)).where(Domain.batch_id == batch_id, Domain.cloudflare_zone_id != None)
                        ) or 0
                        total_propagated = await db.scalar(
                            select(func.count(Domain.id)).where(Domain.batch_id == batch_id, Domain.ns_propagated_at != None)
                        ) or 0

                        batch = await db.get(SetupBatch, batch_id)
                        if batch:
                            batch.ns_propagated_count = total_propagated
                            await db.commit()

                    if job_id in pipeline_jobs:
                        pipeline_jobs[job_id]["steps"]["3"]["completed"] = total_propagated
                        pipeline_jobs[job_id]["steps"]["3"]["total"] = total_zones
                        pipeline_jobs[job_id]["message"] = f"NS propagation: {total_propagated}/{total_zones}"

                    if total_zones and total_propagated and total_propagated >= total_zones * 0.95:
                        logger.info(f"Step 3: {total_propagated}/{total_zones} propagated (≥95%), proceeding")
                        break

                    await asyncio.sleep(30)

                if job_id in pipeline_jobs:
                    pipeline_jobs[job_id]["steps"]["3"]["status"] = "completed"
                await log_activity(batch_id, 3, STEP_NAMES[3], status="completed", message=f"{total_propagated}/{total_zones} propagated")

            except Exception as step_error:
                logger.error(f"Step 3 CRASHED (continuing to next step): {step_error}")
                import traceback
                logger.error(traceback.format_exc())
                await log_activity(batch_id, 3, STEP_NAMES[3], status="error", message=str(step_error))
                if job_id in pipeline_jobs:
                    pipeline_jobs[job_id]["steps"]["3"]["status"] = "error"
                    pipeline_jobs[job_id]["errors"].append({"step": 3, "error": str(step_error)})
        else:
            logger.info(f"Skipping Steps 2-3 (starting from step {start_from_step})")
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["2"]["status"] = "completed"
                pipeline_jobs[job_id]["steps"]["3"]["status"] = "completed"

        # ================================================================
        # STEP 4: Create DNS Records + Redirects
        # ================================================================
        if start_from_step <= 4:
          try:
            await _update_pipeline(batch_id, 4, "running", "Creating DNS records and redirects...")
            await log_activity(batch_id, 4, STEP_NAMES[4], status="started")

            async with SessionLocal() as db:
                # Only process domains that need DNS (skip already-configured re-used domains)
                domains = (await db.execute(
                    select(Domain).where(
                        Domain.batch_id == batch_id,
                        Domain.cloudflare_zone_id.isnot(None),
                        Domain.dns_records_created != True,
                    )
                )).scalars().all()

                dns_done = 0
                for domain in domains:
                    if await _check_paused_or_stopped(batch_id):
                        return

                    try:
                        zone_id = domain.cloudflare_zone_id
                        if not zone_id:
                            continue

                        dns_result = await cloudflare_service.ensure_email_dns_records(zone_id, domain.name)

                        all_ok = all(r["success"] for r in dns_result.values())
                        if all_ok:
                            domain.dns_records_created = True
                            dns_done += 1
                            await log_activity(batch_id, 4, STEP_NAMES[4], "domain", str(domain.id), domain.name, "completed", "DNS records ensured")
                        else:
                            errors = [f"{k}: {v['error']}" for k, v in dns_result.items() if v.get("error")]
                            domain.error_message = "; ".join(errors)
                            await log_activity(batch_id, 4, STEP_NAMES[4], "domain", str(domain.id), domain.name, "failed", domain.error_message)

                        if domain.redirect_url and not getattr(domain, 'redirect_configured', False):
                            try:
                                await cloudflare_service.create_redirect_rule(zone_id, domain.name, domain.redirect_url)
                                domain.redirect_configured = True
                            except Exception as re:
                                logger.warning(f"Redirect failed for {domain.name}: {re}")

                    except Exception as e:
                        domain.error_message = str(e)
                        await log_activity(batch_id, 4, STEP_NAMES[4], "domain", str(domain.id), domain.name, "failed", str(e))

                    await db.commit()

                total_dns_done = await db.scalar(
                    select(func.count(Domain.id)).where(
                        Domain.batch_id == batch_id,
                        Domain.dns_records_created == True,
                    )
                ) or 0

                batch = await db.get(SetupBatch, batch_id)
                if batch:
                    batch.dns_completed = total_dns_done
                    await db.commit()

            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["4"]["status"] = "completed"
                pipeline_jobs[job_id]["steps"]["4"]["completed"] = total_dns_done

            logger.info(f"Step 4: {dns_done} new DNS configured, {total_dns_done} total ready")

          except Exception as step_error:
            logger.error(f"Step 4 CRASHED (continuing to next step): {step_error}")
            import traceback
            logger.error(traceback.format_exc())
            await log_activity(batch_id, 4, STEP_NAMES[4], status="error", message=str(step_error))
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["4"]["status"] = "error"
                pipeline_jobs[job_id]["errors"].append({"step": 4, "error": str(step_error)})
        else:
            logger.info(f"Skipping Step 4 (starting from step {start_from_step})")
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["4"]["status"] = "completed"

        # ================================================================
        # STEP 5: First Login Automation (WITH AUTO-RETRY)
        # ================================================================
        if start_from_step <= 5:
          try:
            await _update_pipeline(batch_id, 5, "running", "Running first login automation...")
            await log_activity(batch_id, 5, STEP_NAMES[5], status="started")

            async with SessionLocal() as db:
                batch = await db.get(SetupBatch, batch_id)
                new_password = batch.new_admin_password if batch else "#Sendemails1"

            from app.services.tenant_automation import process_tenants_parallel

            for attempt in range(MAX_PIPELINE_RETRIES + 1):
                if await _check_paused_or_stopped(batch_id):
                    return

                async with SessionLocal() as db:
                    tenants = (await db.execute(
                        select(Tenant).where(
                            Tenant.batch_id == batch_id,
                            Tenant.first_login_completed != True,
                            Tenant.step4_retry_count <= MAX_PIPELINE_RETRIES,
                        )
                    )).scalars().all()

                    if not tenants:
                        logger.info(f"Step 5: All tenants completed first login")
                        break

                    remaining = len(tenants)
                    logger.info(f"Step 5: Attempt {attempt + 1}/{MAX_PIPELINE_RETRIES + 1} — {remaining} tenants remaining")
                    await _update_pipeline(batch_id, 5, "running",
                        f"First login attempt {attempt + 1} — {remaining} tenants remaining...")

                    tenant_data = [
                        {
                            "tenant_id": str(t.id),
                            "admin_email": t.admin_email,
                            "initial_password": t.admin_password,  # KEY MUST BE initial_password
                        }
                        for t in tenants
                    ]

                if tenant_data:
                    try:
                        results = await process_tenants_parallel(tenant_data, new_password, max_workers=STEP5_MAX_WORKERS)

                        async with SessionLocal() as db:
                            for r in results:
                                try:
                                    t = await db.get(Tenant, UUID(r["tenant_id"]))
                                    if not t:
                                        continue
                                    if r.get("success"):
                                        t.admin_password = new_password
                                        t.password_changed = True
                                        t.first_login_completed = True
                                        t.first_login_at = datetime.utcnow()
                                        t.setup_error = None
                                        if r.get("totp_secret") and not t.totp_secret:
                                            t.totp_secret = r["totp_secret"]
                                        await log_activity(batch_id, 5, STEP_NAMES[5], "tenant", str(t.id),
                                            t.custom_domain or t.name, "completed")
                                    else:
                                        t.step4_retry_count = (t.step4_retry_count or 0) + 1
                                        t.setup_error = r.get("error", "Unknown")
                                        if t.step4_retry_count > MAX_PIPELINE_RETRIES:
                                            t.first_login_completed = True
                                            t.setup_error = f"SKIPPED after {MAX_PIPELINE_RETRIES} retries: {r.get('error')}"
                                            await log_activity(batch_id, 5, STEP_NAMES[5], "tenant", str(t.id),
                                                t.custom_domain or t.name, "skipped", t.setup_error)
                                        else:
                                            await log_activity(batch_id, 5, STEP_NAMES[5], "tenant", str(t.id),
                                                t.custom_domain or t.name, "failed", r.get("error"))
                                    await db.commit()
                                except Exception as e:
                                    logger.error(f"Failed to save Step 5 result: {e}")
                    except Exception as e:
                        logger.error(f"Step 5 attempt {attempt + 1} failed: {e}")

                if attempt < MAX_PIPELINE_RETRIES:
                    await asyncio.sleep(10)

            # Final count
            async with SessionLocal() as db:
                login_ok = await db.scalar(
                    select(func.count(Tenant.id)).where(
                        Tenant.batch_id == batch_id, Tenant.first_login_completed == True
                    )
                ) or 0
                batch = await db.get(SetupBatch, batch_id)
                if batch:
                    batch.first_login_completed_count = login_ok
                    await db.commit()

            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["5"]["completed"] = login_ok
                pipeline_jobs[job_id]["steps"]["5"]["status"] = "completed"
            logger.info(f"Step 5 complete: {login_ok} tenants logged in successfully")

          except Exception as step_error:
            logger.error(f"Step 5 CRASHED (continuing to next step): {step_error}")
            import traceback
            logger.error(traceback.format_exc())
            await log_activity(batch_id, 5, STEP_NAMES[5], status="error", message=str(step_error))
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["5"]["status"] = "error"
                pipeline_jobs[job_id]["errors"].append({"step": 5, "error": str(step_error)})
        else:
            logger.info(f"Skipping Step 5 (starting from step {start_from_step})")
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["5"]["status"] = "completed"

        # ================================================================
        # STEP 6: M365 Domain Setup + DKIM (WITH AUTO-RETRY)
        # ================================================================
        if start_from_step <= 6:
          try:
            await _update_pipeline(batch_id, 6, "running", "Adding domains to M365 and configuring DKIM...")
            await log_activity(batch_id, 6, STEP_NAMES[6], status="started")

            from app.services.m365_setup import run_step5_for_batch as run_m365_setup

            for attempt in range(MAX_PIPELINE_RETRIES + 1):
                if await _check_paused_or_stopped(batch_id):
                    return

                async with SessionLocal() as db:
                    pending_m365 = await db.scalar(
                        select(func.count(Tenant.id)).where(
                            Tenant.batch_id == batch_id,
                            Tenant.first_login_completed == True,
                            Tenant.domain_verified_in_m365 != True,
                            Tenant.step5_retry_count <= MAX_PIPELINE_RETRIES,
                        )
                    ) or 0

                if pending_m365 == 0:
                    logger.info("Step 6: All tenants have M365 domains configured")
                    break

                logger.info(f"Step 6: Attempt {attempt + 1}/{MAX_PIPELINE_RETRIES + 1} — {pending_m365} tenants remaining")
                await _update_pipeline(batch_id, 6, "running",
                    f"M365 setup attempt {attempt + 1} — {pending_m365} tenants remaining...")

                try:
                    m365_result = await run_m365_setup(batch_id)
                    logger.info(f"Step 6 attempt {attempt + 1} result: {m365_result.get('processed', 0)} processed, {m365_result.get('failed', 0)} failed")
                except Exception as e:
                    logger.error(f"Step 6 attempt {attempt + 1} failed: {e}")

                async with SessionLocal() as db:
                    failed_tenants = (await db.execute(
                        select(Tenant).where(
                            Tenant.batch_id == batch_id,
                            Tenant.first_login_completed == True,
                            Tenant.domain_verified_in_m365 != True,
                        )
                    )).scalars().all()
                    for t in failed_tenants:
                        t.step5_retry_count = (t.step5_retry_count or 0) + 1
                        if t.step5_retry_count > MAX_PIPELINE_RETRIES:
                            t.domain_verified_in_m365 = True
                            t.setup_error = f"SKIPPED M365 setup after {MAX_PIPELINE_RETRIES} retries"
                            await log_activity(batch_id, 6, STEP_NAMES[6], "tenant", str(t.id),
                                t.custom_domain or t.name, "skipped", t.setup_error)
                    await db.commit()

                if attempt < MAX_PIPELINE_RETRIES:
                    await asyncio.sleep(10)

            async with SessionLocal() as db:
                m365_ok = await db.scalar(
                    select(func.count(Tenant.id)).where(
                        Tenant.batch_id == batch_id, Tenant.domain_verified_in_m365 == True
                    )
                ) or 0
                batch = await db.get(SetupBatch, batch_id)
                if batch:
                    batch.m365_completed = m365_ok
                    await db.commit()

            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["6"]["completed"] = m365_ok
                pipeline_jobs[job_id]["steps"]["6"]["status"] = "completed"
            logger.info(f"Step 6 complete: {m365_ok} tenants M365 configured")

          except Exception as step_error:
            logger.error(f"Step 6 CRASHED (continuing to next step): {step_error}")
            import traceback
            logger.error(traceback.format_exc())
            await log_activity(batch_id, 6, STEP_NAMES[6], status="error", message=str(step_error))
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["6"]["status"] = "error"
                pipeline_jobs[job_id]["errors"].append({"step": 6, "error": str(step_error)})
        else:
            logger.info(f"Skipping Step 6 (starting from step {start_from_step})")
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["6"]["status"] = "completed"

        # ================================================================
        # STEP 7: Create Mailboxes + Delegate (WITH AUTO-RETRY)
        # ================================================================
        if start_from_step <= 7:
          try:
            await _update_pipeline(batch_id, 7, "running", "Creating mailboxes and delegation...")
            await log_activity(batch_id, 7, STEP_NAMES[7], status="started")

            async with SessionLocal() as db:
                batch = await db.get(SetupBatch, batch_id)
                display_name = f"{batch.persona_first_name or ''} {batch.persona_last_name or ''}".strip() if batch else ""

            from app.services.azure_step6 import run_step6_for_batch as run_mailbox_creation

            for attempt in range(MAX_PIPELINE_RETRIES + 1):
                if await _check_paused_or_stopped(batch_id):
                    return

                async with SessionLocal() as db:
                    pending_mb = await db.scalar(
                        select(func.count(Tenant.id)).where(
                            Tenant.batch_id == batch_id,
                            Tenant.domain_verified_in_m365 == True,
                            Tenant.step6_complete != True,
                            Tenant.step6_retry_count <= MAX_PIPELINE_RETRIES,
                        )
                    ) or 0

                if pending_mb == 0:
                    logger.info("Step 7: All tenants have mailboxes created")
                    break

                logger.info(f"Step 7: Attempt {attempt + 1}/{MAX_PIPELINE_RETRIES + 1} — {pending_mb} tenants remaining")
                await _update_pipeline(batch_id, 7, "running",
                    f"Mailbox creation attempt {attempt + 1} — {pending_mb} tenants remaining...")

                try:
                    await run_mailbox_creation(batch_id, display_name)
                except Exception as e:
                    logger.error(f"Step 7 attempt {attempt + 1} failed: {e}")

                async with SessionLocal() as db:
                    failed_tenants = (await db.execute(
                        select(Tenant).where(
                            Tenant.batch_id == batch_id,
                            Tenant.domain_verified_in_m365 == True,
                            Tenant.step6_complete != True,
                        )
                    )).scalars().all()
                    for t in failed_tenants:
                        t.step6_retry_count = (t.step6_retry_count or 0) + 1
                        if t.step6_retry_count > MAX_PIPELINE_RETRIES:
                            t.step6_complete = True
                            t.step6_error = f"SKIPPED after {MAX_PIPELINE_RETRIES} retries"
                            await log_activity(batch_id, 7, STEP_NAMES[7], "tenant", str(t.id),
                                t.custom_domain or t.name, "skipped", t.step6_error)
                    await db.commit()

                if attempt < MAX_PIPELINE_RETRIES:
                    await asyncio.sleep(15)

            async with SessionLocal() as db:
                mb_complete = await db.scalar(
                    select(func.count(Tenant.id)).where(
                        Tenant.batch_id == batch_id, Tenant.step6_complete == True
                    )
                ) or 0
                batch = await db.get(SetupBatch, batch_id)
                if batch:
                    batch.mailboxes_completed_count = mb_complete
                    await db.commit()

            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["7"]["completed"] = mb_complete
                pipeline_jobs[job_id]["steps"]["7"]["status"] = "completed"
            logger.info(f"Step 7 complete: {mb_complete} tenants mailboxes created")

          except Exception as step_error:
            logger.error(f"Step 7 CRASHED (continuing to next step): {step_error}")
            import traceback
            logger.error(traceback.format_exc())
            await log_activity(batch_id, 7, STEP_NAMES[7], status="error", message=str(step_error))
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["7"]["status"] = "error"
                pipeline_jobs[job_id]["errors"].append({"step": 7, "error": str(step_error)})
        else:
            logger.info(f"Skipping Step 7 (starting from step {start_from_step})")
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["7"]["status"] = "completed"

        # ================================================================
        # STEP 8: Enable SMTP Auth (WITH AUTO-RETRY)
        # ================================================================
        if start_from_step <= 8:
          try:
            await _update_pipeline(batch_id, 8, "running", "Enabling SMTP authentication...")
            await log_activity(batch_id, 8, STEP_NAMES[8], status="started")

            for attempt in range(MAX_PIPELINE_RETRIES + 1):
                if await _check_paused_or_stopped(batch_id):
                    return

                tenant_list = []
                async with SessionLocal() as db:
                    tenants = (await db.execute(
                        select(Tenant).where(
                            Tenant.batch_id == batch_id,
                            Tenant.step6_complete == True,
                            Tenant.step7_complete != True,
                            Tenant.step7_retry_count <= MAX_PIPELINE_RETRIES,
                        )
                    )).scalars().all()

                    if not tenants:
                        logger.info("Step 8: All tenants have SMTP auth enabled")
                        break

                    for t in tenants:
                        tenant_list.append({
                            "id": t.id,
                            "admin_email": t.admin_email,
                            "admin_password": t.admin_password,
                            "totp_secret": t.totp_secret,
                            "domain": t.custom_domain or t.name,
                        })

                remaining = len(tenant_list)
                logger.info(f"Step 8: Attempt {attempt + 1}/{MAX_PIPELINE_RETRIES + 1} — {remaining} tenants remaining")
                await _update_pipeline(batch_id, 8, "running",
                    f"SMTP auth attempt {attempt + 1} — {remaining} tenants remaining...")

                for td in tenant_list:
                    if await _check_paused_or_stopped(batch_id):
                        return

                    try:
                        result = await enable_org_smtp_auth(
                            admin_email=td["admin_email"],
                            admin_password=td["admin_password"],
                            totp_secret=td["totp_secret"],
                            domain=td["domain"],
                        )
                    except Exception as e:
                        result = {"success": False, "error": str(e)}

                    async with SessionLocal() as db:
                        tenant = await db.get(Tenant, td["id"])
                        if not tenant:
                            continue
                        if result.get("success"):
                            tenant.step7_complete = True
                            tenant.step7_smtp_auth_enabled = True
                            await log_activity(batch_id, 8, STEP_NAMES[8], "tenant", str(tenant.id),
                                td["domain"], "completed")
                        else:
                            tenant.step7_retry_count = (tenant.step7_retry_count or 0) + 1
                            tenant.step7_error = result.get("error")
                            if tenant.step7_retry_count > MAX_PIPELINE_RETRIES:
                                tenant.step7_complete = True
                                tenant.step7_error = f"SKIPPED after {MAX_PIPELINE_RETRIES} retries: {result.get('error')}"
                                await log_activity(batch_id, 8, STEP_NAMES[8], "tenant", str(tenant.id),
                                    td["domain"], "skipped", tenant.step7_error)
                            else:
                                await log_activity(batch_id, 8, STEP_NAMES[8], "tenant", str(tenant.id),
                                    td["domain"], "failed", result.get("error"))
                        await db.commit()

                if attempt < MAX_PIPELINE_RETRIES:
                    await asyncio.sleep(10)

            async with SessionLocal() as db:
                smtp_ok = await db.scalar(
                    select(func.count(Tenant.id)).where(
                        Tenant.batch_id == batch_id, Tenant.step7_complete == True
                    )
                ) or 0
                batch = await db.get(SetupBatch, batch_id)
                if batch:
                    batch.smtp_completed = smtp_ok
                    await db.commit()

            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["8"]["completed"] = smtp_ok
                pipeline_jobs[job_id]["steps"]["8"]["status"] = "completed"
            logger.info(f"Step 8 complete: {smtp_ok} tenants SMTP auth enabled")

          except Exception as step_error:
            logger.error(f"Step 8 CRASHED (continuing to next step): {step_error}")
            import traceback
            logger.error(traceback.format_exc())
            await log_activity(batch_id, 8, STEP_NAMES[8], status="error", message=str(step_error))
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["8"]["status"] = "error"
                pipeline_jobs[job_id]["errors"].append({"step": 8, "error": str(step_error)})
        else:
            logger.info(f"Skipping Step 8 (starting from step {start_from_step})")
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["8"]["status"] = "completed"

        # ================================================================
        # STEP 9: Export Credentials (auto-generated)
        # ================================================================
        if start_from_step <= 9:
          try:
            await _update_pipeline(batch_id, 9, "running", "Generating credentials export...")
            await log_activity(batch_id, 9, STEP_NAMES[9], status="started")
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["9"]["status"] = "completed"
            await log_activity(batch_id, 9, STEP_NAMES[9], status="completed", message="Credentials available for download")
          except Exception as step_error:
            logger.error(f"Step 9 CRASHED: {step_error}")
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["9"]["status"] = "error"
                pipeline_jobs[job_id]["errors"].append({"step": 9, "error": str(step_error)})
        else:
            logger.info(f"Skipping Step 9 (starting from step {start_from_step})")
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["9"]["status"] = "completed"

        # ================================================================
        # STEP 10: Upload to Sequencer (OAuth)
        # ================================================================
        if start_from_step <= 10:
          try:
            async with SessionLocal() as db:
                batch = await db.get(SetupBatch, batch_id)
                has_sequencer = batch and batch.sequencer_platform and batch.sequencer_login_email

            if has_sequencer:
                await _update_pipeline(batch_id, 10, "running", "Uploading to sequencer...")
                await log_activity(batch_id, 10, STEP_NAMES[10], status="started")
                logger.info("Step 10: Sequencer upload not yet implemented — skipping")
                await log_activity(batch_id, 10, STEP_NAMES[10], status="skipped", message="Sequencer upload not yet implemented")
                if job_id in pipeline_jobs:
                    pipeline_jobs[job_id]["steps"]["10"]["status"] = "skipped"
            else:
                logger.info("Step 10: No sequencer configured — skipping")
                if job_id in pipeline_jobs:
                    pipeline_jobs[job_id]["steps"]["10"]["status"] = "skipped"
          except Exception as step_error:
            logger.error(f"Step 10 CRASHED: {step_error}")
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["10"]["status"] = "error"
                pipeline_jobs[job_id]["errors"].append({"step": 10, "error": str(step_error)})
        else:
            logger.info(f"Skipping Step 10 (starting from step {start_from_step})")
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["10"]["status"] = "skipped"

        # ================================================================
        # PIPELINE COMPLETE
        # ================================================================
        await _update_pipeline(batch_id, 10, "completed", "Pipeline complete!")

        async with SessionLocal() as db:
            batch = await db.get(SetupBatch, batch_id)
            if batch:
                batch.pipeline_status = "completed"
                batch.pipeline_completed_at = datetime.utcnow()
                batch.status = BatchStatus.COMPLETED
                await db.commit()

        if job_id in pipeline_jobs:
            pipeline_jobs[job_id]["status"] = "completed"
            pipeline_jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()

        logger.info(f"✅ Pipeline COMPLETE for batch {batch_id}")
        await log_activity(batch_id, 10, "Pipeline Complete", status="completed", message="All steps finished")

    except Exception as e:
        logger.error(f"💥 Pipeline CRASHED: {e}")
        import traceback
        logger.error(traceback.format_exc())

        await _update_pipeline(batch_id, 0, "error", f"Pipeline error: {str(e)}")

        if job_id in pipeline_jobs:
            pipeline_jobs[job_id]["status"] = "error"
            pipeline_jobs[job_id]["error"] = str(e)

        async with SessionLocal() as db:
            batch = await db.get(SetupBatch, batch_id)
            if batch:
                batch.pipeline_status = "error"
                await db.commit()


# Helper to log pipeline activity
async def log_activity(
    batch_id,
    step,
    step_name,
    item_type=None,
    item_id=None,
    item_name=None,
    status="started",
    message=None,
    error=None,
):
    """Write to both PipelineLog table and in-memory job."""
    try:
        async with SessionLocal() as db:
            log = PipelineLog(
                batch_id=batch_id,
                step=step,
                step_name=step_name,
                item_type=item_type,
                item_id=item_id,
                item_name=item_name,
                status=status,
                message=message,
                error_detail=error,
            )
            db.add(log)
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to write pipeline log: {e}")

    # Also update in-memory
    job_id = str(batch_id)
    if job_id in pipeline_jobs:
        pipeline_jobs[job_id]["activity_log"].insert(0, {
            "step": step,
            "step_name": step_name,
            "item_name": item_name,
            "status": status,
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
        })
        # Keep only last 50 entries in memory
        pipeline_jobs[job_id]["activity_log"] = pipeline_jobs[job_id]["activity_log"][:50]


async def resume_interrupted_pipelines():
    """Resume pipelines that were running when the container restarted."""
    try:
        async with SessionLocal() as db:
            running_batches = (await db.execute(
                select(SetupBatch).where(
                    SetupBatch.pipeline_status == "running"
                )
            )).scalars().all()

            for batch in running_batches:
                logger.warning(f"Found interrupted pipeline for batch {batch.id} (was on step {batch.pipeline_step})")
                # Don't auto-resume — mark as paused so user can manually resume
                batch.pipeline_status = "paused"
                batch.pipeline_step_name = f"Interrupted at: {batch.pipeline_step_name or 'Unknown'}"
                await db.commit()
                logger.info(f"Marked batch {batch.id} as paused — user can resume from dashboard")
    except Exception as e:
        logger.error(f"Failed to check for interrupted pipelines: {e}")
