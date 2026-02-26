"""
Pipeline API — Collect-everything-upfront, then execute automatically.
"""
import asyncio
import logging
import os
import random
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

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

    # Import domains
    for d in domains:
        # Extract TLD from domain name
        parts = d["name"].rsplit(".", 1)
        tld = parts[-1] if len(parts) > 1 else ""

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
        "domains_imported": len(domains),
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
async def confirm_nameservers(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """User confirms they've updated nameservers at Porkbun. Resumes pipeline."""
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")

    batch.ns_confirmed_at = datetime.utcnow()
    await db.commit()

    # Signal the pipeline to resume (it's polling for ns_confirmed_at)
    job_id = str(batch_id)
    if job_id in pipeline_jobs:
        pipeline_jobs[job_id]["ns_confirmed"] = True
        pipeline_jobs[job_id]["message"] = "Nameservers confirmed — checking propagation..."

    return {"success": True, "message": "Nameservers confirmed. Pipeline will resume automatically."}


@router.post("/{batch_id}/retry-failed")
async def retry_failed(
    batch_id: UUID,
    step: int = None,  # Optional: retry only a specific step
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
):
    """Retry failed items. Optionally specify a step number to retry only that step."""
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")

    # Count failed items
    failed_tenants = (await db.execute(
        select(Tenant).where(
            Tenant.batch_id == batch_id,
            Tenant.setup_error != None,
        )
    )).scalars().all()

    # Clear errors for retry
    for t in failed_tenants:
        t.setup_error = None
        if step == 5 or step is None:
            if not t.first_login_completed:
                t.first_login_completed = False
        if step == 6 or step is None:
            if not t.step5_complete:
                t.step5_complete = False
        if step == 7 or step is None:
            if not t.step6_complete:
                t.step6_started = False
                t.step6_error = None

    await db.commit()

    # Re-launch pipeline from the appropriate step
    if step:
        batch.pipeline_step = step

    batch.pipeline_status = "running"
    await db.commit()

    background_tasks.add_task(run_pipeline, batch_id)

    return {
        "success": True,
        "message": f"Retrying {len(failed_tenants)} failed items" + (f" from step {step}" if step else ""),
        "failed_count": len(failed_tenants),
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
async def resume_pipeline(batch_id: UUID, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Resume a paused pipeline."""
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")

    batch.pipeline_status = "running"
    batch.pipeline_paused_at = None
    await db.commit()

    job_id = str(batch_id)
    if job_id in pipeline_jobs:
        pipeline_jobs[job_id]["status"] = "running"
        pipeline_jobs[job_id]["message"] = "Pipeline resumed"

    # Re-launch pipeline from current step
    background_tasks.add_task(run_pipeline, batch_id)

    return {"success": True, "message": f"Pipeline resumed from step {batch.pipeline_step}"}


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


async def run_pipeline(batch_id: UUID):
    """
    MAIN PIPELINE ORCHESTRATOR.

    Runs Steps 1-10 sequentially, pausing only at Step 2 (NS update).
    Each step calls existing service functions.
    Errors on individual items don't block the pipeline — they're logged and the item is skipped.
    """
    job_id = str(batch_id)
    logger.info(f"🚀 Pipeline started for batch {batch_id}")

    try:
        # ================================================================
        # STEP 1: Create Cloudflare Zones
        # ================================================================
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

            # Update batch counters
            batch = await db.get(SetupBatch, batch_id)
            if batch:
                batch.zones_completed = zones_created
                await db.commit()

        # Store NS groups in job for frontend display
        if job_id in pipeline_jobs:
            pipeline_jobs[job_id]["nameserver_groups"] = [
                {"nameservers": ns.split(","), "domains": doms, "count": len(doms)}
                for ns, doms in ns_groups.items()
            ]
            pipeline_jobs[job_id]["steps"]["1"]["status"] = "completed"
            pipeline_jobs[job_id]["steps"]["1"]["completed"] = zones_created
            pipeline_jobs[job_id]["steps"]["1"]["failed"] = zones_failed

        logger.info(f"Step 1 complete: {zones_created} zones created, {zones_failed} failed")

        # ================================================================
        # STEP 2: Pause for Nameserver Update (ONLY MANUAL STEP)
        # ================================================================
        await _update_pipeline(batch_id, 2, "paused", "Waiting for nameserver update confirmation...")
        await log_activity(batch_id, 2, STEP_NAMES[2], status="started", message="Waiting for user to update nameservers at Porkbun")

        if job_id in pipeline_jobs:
            pipeline_jobs[job_id]["steps"]["2"]["status"] = "waiting_for_user"

        # Poll for NS confirmation (user clicks "Confirm Nameservers" in UI)
        while True:
            if await _check_paused_or_stopped(batch_id):
                return

            # Check if user confirmed
            async with SessionLocal() as db:
                batch = await db.get(SetupBatch, batch_id)
                if batch and batch.ns_confirmed_at:
                    break

            # Also check in-memory flag
            if job_id in pipeline_jobs and pipeline_jobs[job_id].get("ns_confirmed"):
                break

            await asyncio.sleep(5)  # Poll every 5 seconds

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
        max_propagation_checks = 60  # 60 checks * 30s = 30 minutes max

        for check_round in range(max_propagation_checks):
            if await _check_paused_or_stopped(batch_id):
                return

            async with SessionLocal() as db:
                # Find domains with zones that haven't propagated yet
                # (status is not NS_PROPAGATED and ns_propagated_at is None)
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
                        # Use get_zone_status which returns "active" or "pending"
                        zone_status = await cloudflare_service.get_zone_status(domain.cloudflare_zone_id)
                        if zone_status == "active":
                            domain.status = DomainStatus.NS_PROPAGATED
                            domain.ns_propagated_at = datetime.utcnow()
                            domain.nameservers_updated = True
                            await log_activity(batch_id, 3, STEP_NAMES[3], "domain", str(domain.id), domain.name, "completed", "NS propagated")
                    except Exception as e:
                        logger.warning(f"Propagation check failed for {domain.name}: {e}")

                await db.commit()

                # Update counters
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

            # Proceed if 95%+ propagated
            if total_zones and total_propagated and total_propagated >= total_zones * 0.95:
                logger.info(f"Step 3: {total_propagated}/{total_zones} propagated (≥95%), proceeding")
                break

            await asyncio.sleep(30)  # Check every 30 seconds

        if job_id in pipeline_jobs:
            pipeline_jobs[job_id]["steps"]["3"]["status"] = "completed"
        await log_activity(batch_id, 3, STEP_NAMES[3], status="completed", message=f"{total_propagated}/{total_zones} propagated")

        # ================================================================
        # STEP 4: Create DNS Records + Redirects
        # ================================================================
        await _update_pipeline(batch_id, 4, "running", "Creating DNS records and redirects...")
        await log_activity(batch_id, 4, STEP_NAMES[4], status="started")

        async with SessionLocal() as db:
            domains = (await db.execute(
                select(Domain).where(
                    Domain.batch_id == batch_id,
                    Domain.ns_propagated_at != None,
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

                    # MX record
                    await cloudflare_service.create_dns_record(
                        zone_id, "MX", domain.name,
                        f"{domain.name.replace('.', '-')}.mail.protection.outlook.com",
                        priority=0, proxied=False
                    )

                    # SPF record
                    await cloudflare_service.create_dns_record(
                        zone_id, "TXT", domain.name,
                        "v=spf1 include:spf.protection.outlook.com -all",
                        proxied=False
                    )

                    # Autodiscover CNAME
                    await cloudflare_service.create_dns_record(
                        zone_id, "CNAME", f"autodiscover.{domain.name}",
                        "autodiscover.outlook.com",
                        proxied=False
                    )

                    # Redirect rule (if redirect_url provided)
                    if domain.redirect_url:
                        try:
                            await cloudflare_service.create_redirect_rule(
                                zone_id, domain.name, domain.redirect_url
                            )
                            domain.redirect_configured = True
                        except Exception as re:
                            logger.warning(f"Redirect failed for {domain.name}: {re}")

                    domain.dns_records_created = True
                    dns_done += 1
                    await log_activity(batch_id, 4, STEP_NAMES[4], "domain", str(domain.id), domain.name, "completed", "DNS records created")

                except Exception as e:
                    domain.error_message = str(e)
                    await log_activity(batch_id, 4, STEP_NAMES[4], "domain", str(domain.id), domain.name, "failed", str(e))

                await db.commit()

            batch = await db.get(SetupBatch, batch_id)
            if batch:
                batch.dns_completed = dns_done
                await db.commit()

        if job_id in pipeline_jobs:
            pipeline_jobs[job_id]["steps"]["4"]["status"] = "completed"
            pipeline_jobs[job_id]["steps"]["4"]["completed"] = dns_done

        # ================================================================
        # STEP 5: First Login Automation
        # ================================================================
        await _update_pipeline(batch_id, 5, "running", "Running first login automation...")
        await log_activity(batch_id, 5, STEP_NAMES[5], status="started")

        async with SessionLocal() as db:
            batch = await db.get(SetupBatch, batch_id)
            new_password = batch.new_admin_password if batch else None

        if new_password:
            # Import the existing Step 4 processing function
            from app.services.tenant_automation import process_tenants_parallel

            async with SessionLocal() as db:
                tenants = (await db.execute(
                    select(Tenant).where(
                        Tenant.batch_id == batch_id,
                        Tenant.first_login_completed != True,
                    )
                )).scalars().all()

                tenant_data = [
                    {
                        "tenant_id": str(t.id),
                        "admin_email": t.admin_email,
                        "admin_password": t.admin_password,
                    }
                    for t in tenants
                ]

            if tenant_data:
                results = await process_tenants_parallel(tenant_data, new_password, max_workers=2)

                # Save results
                async with SessionLocal() as db:
                    login_ok = 0
                    login_fail = 0
                    for r in results:
                        try:
                            t = await db.get(Tenant, UUID(r["tenant_id"]))
                            if t and r.get("success"):
                                t.admin_password = new_password
                                t.password_changed = True
                                t.first_login_completed = True
                                t.first_login_at = datetime.utcnow()
                                t.setup_error = None
                                if r.get("totp_secret") and not t.totp_secret:
                                    t.totp_secret = r["totp_secret"]
                                login_ok += 1
                                await log_activity(batch_id, 5, STEP_NAMES[5], "tenant", str(t.id), t.custom_domain or t.name, "completed")
                            elif t:
                                t.setup_error = r.get("error", "Unknown")
                                login_fail += 1
                                await log_activity(batch_id, 5, STEP_NAMES[5], "tenant", str(t.id), t.custom_domain or t.name, "failed", r.get("error"))
                            await db.commit()
                        except Exception as e:
                            logger.error(f"Failed to save Step 5 result: {e}")

                    batch = await db.get(SetupBatch, batch_id)
                    if batch:
                        batch.first_login_completed_count = login_ok
                        await db.commit()

                if job_id in pipeline_jobs:
                    pipeline_jobs[job_id]["steps"]["5"]["completed"] = login_ok
                    pipeline_jobs[job_id]["steps"]["5"]["failed"] = login_fail

        if job_id in pipeline_jobs:
            pipeline_jobs[job_id]["steps"]["5"]["status"] = "completed"

        # ================================================================
        # STEP 6: M365 Domain Setup + DKIM
        # ================================================================
        await _update_pipeline(batch_id, 6, "running", "Adding domains to M365 and configuring DKIM...")
        await log_activity(batch_id, 6, STEP_NAMES[6], status="started")

        from app.services.m365_setup import run_step5_for_batch as run_m365_setup

        try:
            m365_result = await run_m365_setup(batch_id)
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["6"]["completed"] = m365_result.get("processed", 0)
                pipeline_jobs[job_id]["steps"]["6"]["failed"] = m365_result.get("failed", 0)
                pipeline_jobs[job_id]["steps"]["6"]["status"] = "completed"

            async with SessionLocal() as db:
                batch = await db.get(SetupBatch, batch_id)
                if batch:
                    batch.m365_completed = m365_result.get("processed", 0)
                    await db.commit()
        except Exception as e:
            logger.error(f"Step 6 failed: {e}")
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["6"]["status"] = "error"
                pipeline_jobs[job_id]["errors"].append({"step": 6, "error": str(e)})

        # ================================================================
        # STEP 7: Create Mailboxes + Delegate
        # ================================================================
        await _update_pipeline(batch_id, 7, "running", "Creating mailboxes and delegation...")
        await log_activity(batch_id, 7, STEP_NAMES[7], status="started")

        async with SessionLocal() as db:
            batch = await db.get(SetupBatch, batch_id)
            display_name = f"{batch.persona_first_name or ''} {batch.persona_last_name or ''}".strip() if batch else ""

        from app.services.azure_step6 import run_step6_for_batch as run_mailbox_creation

        try:
            await run_mailbox_creation(batch_id, display_name)

            # Count actual completions
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
        except Exception as e:
            logger.error(f"Step 7 failed: {e}")
            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["7"]["status"] = "error"
                pipeline_jobs[job_id]["errors"].append({"step": 7, "error": str(e)})

        # ================================================================
        # STEP 8: Enable SMTP Auth
        # ================================================================
        await _update_pipeline(batch_id, 8, "running", "Enabling SMTP authentication...")
        await log_activity(batch_id, 8, STEP_NAMES[8], status="started")

        async with SessionLocal() as db:
            tenants = (await db.execute(
                select(Tenant).where(
                    Tenant.batch_id == batch_id,
                    Tenant.step6_complete == True,
                    Tenant.step7_complete != True,
                )
            )).scalars().all()

            smtp_ok = 0
            smtp_fail = 0

            for tenant in tenants:
                try:
                    # Call existing SMTP auth function
                    result = await enable_org_smtp_auth(
                        admin_email=tenant.admin_email,
                        admin_password=tenant.admin_password,
                        totp_secret=tenant.totp_secret,
                        domain=tenant.custom_domain or tenant.name,
                    )

                    if result.get("success"):
                        tenant.step7_complete = True
                        smtp_ok += 1
                        await log_activity(batch_id, 8, STEP_NAMES[8], "tenant", str(tenant.id), tenant.custom_domain, "completed")
                    else:
                        tenant.step7_error = result.get("error")
                        smtp_fail += 1
                        await log_activity(batch_id, 8, STEP_NAMES[8], "tenant", str(tenant.id), tenant.custom_domain, "failed", result.get("error"))

                    await db.commit()
                except Exception as e:
                    tenant.step7_error = str(e)
                    smtp_fail += 1
                    await db.commit()

            batch = await db.get(SetupBatch, batch_id)
            if batch:
                batch.smtp_completed = smtp_ok
                await db.commit()

        if job_id in pipeline_jobs:
            pipeline_jobs[job_id]["steps"]["8"]["completed"] = smtp_ok
            pipeline_jobs[job_id]["steps"]["8"]["failed"] = smtp_fail
            pipeline_jobs[job_id]["steps"]["8"]["status"] = "completed"

        # ================================================================
        # STEP 9: Export Credentials (auto-generated)
        # ================================================================
        await _update_pipeline(batch_id, 9, "running", "Generating credentials export...")
        await log_activity(batch_id, 9, STEP_NAMES[9], status="started")

        # Credentials are exported on-demand via the /credentials-export endpoint
        # Just mark this step as complete
        if job_id in pipeline_jobs:
            pipeline_jobs[job_id]["steps"]["9"]["status"] = "completed"
        await log_activity(batch_id, 9, STEP_NAMES[9], status="completed", message="Credentials available for download")

        # ================================================================
        # STEP 10: Upload to Sequencer (OAuth)
        # ================================================================
        async with SessionLocal() as db:
            batch = await db.get(SetupBatch, batch_id)
            has_sequencer = batch and batch.sequencer_platform and batch.sequencer_login_email

        if has_sequencer:
            await _update_pipeline(batch_id, 10, "running", "Uploading to sequencer...")
            await log_activity(batch_id, 10, STEP_NAMES[10], status="started")

            # TODO: Implement sequencer upload using existing Selenium scripts
            # from app.services.selenium.sequencer_upload import upload_to_sequencer
            # This will use the sequencer_platform, sequencer_login_email, sequencer_login_password
            # from the batch, plus each mailbox's email + password

            logger.info("Step 10: Sequencer upload not yet implemented — skipping")
            await log_activity(batch_id, 10, STEP_NAMES[10], status="skipped", message="Sequencer upload not yet implemented")

            if job_id in pipeline_jobs:
                pipeline_jobs[job_id]["steps"]["10"]["status"] = "skipped"
        else:
            logger.info("Step 10: No sequencer configured — skipping")
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
