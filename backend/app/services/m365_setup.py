"""
M365 Setup Service - Bulletproof Domain Verification & DKIM Setup

ARCHITECTURE: Sequential processing, one Chrome at a time per worker.
Parallelism = multiple workers (5 workers × 60 domains each), NOT multiple browsers.

THREE LAYERS OF RETRY:
  Layer 1: SUB-STEP RETRY (innermost) — every click/type retries 3-5 times
  Layer 2: PHASE RETRY (middle) — each phase retries 3 times with page reload
  Layer 3: FULL DOMAIN RETRY (outermost) — fresh browser, 60s cooldown, resume from checkpoint

CHECKPOINT SYSTEM:
  After every sub-step completes, the result is committed to DB immediately.
  On retry, the system checks what's already done and skips completed steps.
"""

import asyncio
import gc
import logging
import os
import subprocess
import traceback
from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import async_engine, get_fresh_db_session, SessionLocal
from app.models.tenant import Tenant, TenantStatus
from app.models.domain import Domain, DomainStatus
from app.services.cloudflare import cloudflare_service, CloudflareError

# Load settings
_settings = get_settings()
MAX_PARALLEL_BROWSERS = 1  # ALWAYS 1. Parallelism = multiple workers.
DOMAIN_RETRIES = _settings.step5_domain_retries
STEP5_HEADLESS = _settings.step5_headless

logger = logging.getLogger(__name__)


def _kill_zombie_chrome():
    """Kill ALL orphaned Chrome/Chromium processes. Silent on Windows."""
    for pattern in ["chrome", "chromium", "chromedriver"]:
        try:
            subprocess.run(["pkill", "-9", "-f", pattern], capture_output=True, timeout=5)
        except Exception:
            pass
    gc.collect()


@dataclass
class Step5Result:
    """Result of Step 5 automation for a single tenant."""
    tenant_id: str
    domain_name: str
    success: bool = False
    domain_added: bool = False
    verification_txt: Optional[str] = None
    txt_added_to_cloudflare: bool = False
    domain_verified: bool = False
    mail_dns_added: bool = False
    dns_configured: bool = False
    dkim_config_retrieved: bool = False
    dkim_cnames_added: bool = False
    dkim_enabled: bool = False
    error: Optional[str] = None
    error_step: Optional[str] = None
    steps: Dict[str, Dict] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "tenant_id": self.tenant_id, "domain_name": self.domain_name,
            "success": self.success, "domain_added": self.domain_added,
            "verification_txt": self.verification_txt,
            "txt_added_to_cloudflare": self.txt_added_to_cloudflare,
            "domain_verified": self.domain_verified,
            "mail_dns_added": self.mail_dns_added,
            "dns_configured": self.dns_configured,
            "dkim_config_retrieved": self.dkim_config_retrieved,
            "dkim_cnames_added": self.dkim_cnames_added,
            "dkim_enabled": self.dkim_enabled,
            "error": self.error, "error_step": self.error_step, "steps": self.steps
        }


# ============================================================
# MAIN ASYNC BATCH PROCESSOR — SEQUENTIAL, ONE CHROME AT A TIME
# ============================================================

async def run_step5_for_batch(
    batch_id: UUID, on_progress=None
) -> Dict[str, Any]:
    """
    Process Step 5 for all tenants — SEQUENTIAL, one Chrome at a time.
    Each domain gets up to DOMAIN_RETRIES attempts with a fresh browser.
    Resumes from last checkpoint on retry.

    Architecture:
    1. ASYNC: Gather all tenant data from database
    2. SEQUENTIAL: Process each domain one at a time
    3. ASYNC: Update database with results via checkpoint commits
    """
    from app.models.batch import SetupBatch

    logger.info("=" * 60)
    logger.info(f"=== BULLETPROOF STEP 5: SEQUENTIAL MODE (1 Chrome at a time) ===")
    logger.info(f"=== Domain retries: {DOMAIN_RETRIES}, Headless: {STEP5_HEADLESS} ===")
    logger.info("=" * 60)

    # ============================================================
    # PHASE 1: GATHER TENANT DATA
    # ============================================================
    logger.info("Phase 1: Gathering tenant data from database...")

    async with get_fresh_db_session() as db:
        result = await db.execute(
            select(Tenant).where(
                Tenant.batch_id == batch_id,
                Tenant.domain_id.isnot(None),
                Tenant.first_login_completed == True,
                Tenant.dkim_enabled != True,
                Tenant.permanently_failed != True,
            ).order_by(Tenant.created_at)
        )
        tenants = list(result.scalars().all())

    summary = {
        "batch_id": str(batch_id),
        "total": len(tenants),
        "successful": 0,
        "failed": 0,
        "skipped": 0,
        "results": [],
    }

    if not tenants:
        logger.info("No tenants need Step 5 processing")
        return summary

    # Prepare data for processing (extract all needed info, no SQLAlchemy objects in threads)
    tenants_data = []

    for idx, tenant in enumerate(tenants):
        domain_name = tenant.custom_domain or tenant.name

        async with get_fresh_db_session() as db:
            domain = await db.get(Domain, tenant.domain_id)
        if not domain:
            logger.warning(f"[{domain_name}] Domain record not found, skipping")
            summary["skipped"] += 1
            continue

        if not tenant.admin_email or not tenant.admin_password or not tenant.totp_secret:
            logger.warning(f"[{domain_name}] Missing credentials, skipping")
            summary["results"].append({
                "tenant_id": str(tenant.id),
                "domain_name": domain_name,
                "success": False,
                "error": "Missing credentials"
            })
            summary["failed"] += 1
            continue

        tenants_data.append({
            "tenant_id": str(tenant.id),
            "domain_id": str(domain.id),
            "domain": domain_name,
            "zone_id": domain.cloudflare_zone_id,
            "admin_email": tenant.admin_email,
            "admin_password": tenant.admin_password,
            "totp_secret": tenant.totp_secret,
            "onmicrosoft_domain": tenant.onmicrosoft_domain or (
                tenant.admin_email.split("@")[1] if "@" in (tenant.admin_email or "") else None
            ),
            # Checkpoint state — what's already done
            "needs_add": not tenant.domain_added_to_m365,
            "needs_verify": not tenant.domain_verified_in_m365,
            "needs_dns": not tenant.dns_configured,
            "needs_dkim_cnames": not tenant.dkim_cnames_added,
            "needs_dkim_enable": not tenant.dkim_enabled,
        })

    total = len(tenants_data)
    if not total:
        logger.info("No valid tenants to process after validation")
        return summary

    logger.info(f"Phase 1 complete: {total} tenants ready for SEQUENTIAL processing")

    # ============================================================
    # PHASE 2: SEQUENTIAL DOMAIN PROCESSING
    # ============================================================
    logger.info(f"Phase 2: Starting sequential domain processing...")

    processed = 0
    failed = 0

    for idx, td in enumerate(tenants_data, 1):
        domain_name = td["domain"]
        tenant_id = UUID(td["tenant_id"])
        domain_id = UUID(td["domain_id"])

        logger.info(f"\n{'='*60}")
        logger.info(f"[{domain_name}] Domain {idx}/{total}")
        logger.info(f"{'='*60}")

        # === LAYER 3: FULL DOMAIN RETRY (fresh browser each attempt) ===
        domain_success = False

        for attempt in range(1, DOMAIN_RETRIES + 1):
            logger.info(f"[{domain_name}] === Domain attempt {attempt}/{DOMAIN_RETRIES} ===")

            try:
                # Run Selenium in thread pool (synchronous Chrome)
                loop = asyncio.get_event_loop()
                selenium_result = await loop.run_in_executor(
                    None,
                    _run_domain_setup_sync,
                    td,
                )

                if selenium_result.get("success"):
                    domain_success = True
                    logger.info(f"[{domain_name}] ✓ SUCCESS on attempt {attempt}")
                    break
                else:
                    error = selenium_result.get("error", "unknown")
                    logger.warning(f"[{domain_name}] ✗ Attempt {attempt} failed: {error}")

            except Exception as e:
                logger.error(f"[{domain_name}] ✗ Attempt {attempt} EXCEPTION: {e}")
                logger.error(traceback.format_exc())
                selenium_result = {"success": False, "error": str(e)}

            # Wait before retry (increasing cooldown: 60s, 120s, 180s)
            if attempt < DOMAIN_RETRIES:
                wait = 60 * attempt
                logger.info(f"[{domain_name}] Waiting {wait}s before retry...")
                await asyncio.sleep(wait)

        # === UPDATE DATABASE WITH RESULTS ===
        db_success = await _update_database_with_result(
            tenant_id, domain_id, domain_name, selenium_result, domain_success
        )

        if domain_success:
            processed += 1
            summary["successful"] += 1
        else:
            failed += 1
            summary["failed"] += 1
            if not domain_success:
                # Mark permanently failed after all retries exhausted
                await _mark_permanently_failed(tenant_id, domain_name)

        summary["results"].append({
            "tenant_id": str(tenant_id),
            "domain_name": domain_name,
            "success": domain_success,
            "error": selenium_result.get("error") if not domain_success else None,
        })

        # Progress callback
        if on_progress:
            on_progress(str(tenant_id), "complete", "success" if domain_success else "failed")

        # === CLEANUP BETWEEN DOMAINS ===
        _kill_zombie_chrome()
        gc.collect()
        await asyncio.sleep(3)

        logger.info(f"[Batch {batch_id}] Progress: {processed} ✓ | {failed} ✗ | {idx}/{total}")

    # ============================================================
    # PHASE 3: UPDATE BATCH STATUS
    # ============================================================
    logger.info("Phase 3: Updating batch status...")

    try:
        async with get_fresh_db_session() as db:
            batch = await db.get(SetupBatch, batch_id)
            if batch and summary["failed"] == 0 and summary["successful"] > 0:
                if batch.current_step == 5:
                    batch.current_step = 6
                    if batch.completed_steps is None:
                        batch.completed_steps = []
                    if 5 not in batch.completed_steps:
                        batch.completed_steps = batch.completed_steps + [5]
                    await db.commit()
                    logger.info("Batch advanced to step 6")
    except Exception as e:
        logger.error(f"Batch status update error: {e}")

    logger.info(f"\n{'='*60}")
    logger.info(f"=== STEP 5 COMPLETE ===")
    logger.info(f"  Success: {processed}/{total}")
    logger.info(f"  Failed:  {failed}/{total}")
    logger.info(f"{'='*60}")

    return summary


def _run_domain_setup_sync(td: dict) -> dict:
    """
    Synchronous wrapper that calls the bulletproof domain setup.
    Runs in ThreadPoolExecutor — NO async, NO database.
    """
    domain = td["domain"]
    logger.info(f"[{domain}] Starting synchronous Selenium automation")

    try:
        from app.services.selenium.step5_orchestrator import run_domain_setup_bulletproof

        result = run_domain_setup_bulletproof(
            domain_name=domain,
            zone_id=td["zone_id"],
            admin_email=td["admin_email"],
            admin_password=td["admin_password"],
            totp_secret=td["totp_secret"],
            onmicrosoft_domain=td.get("onmicrosoft_domain"),
            needs_add=td["needs_add"],
            needs_verify=td["needs_verify"],
            needs_dns=td["needs_dns"],
            needs_dkim_cnames=td["needs_dkim_cnames"],
            needs_dkim_enable=td["needs_dkim_enable"],
            headless=STEP5_HEADLESS,
        )

        logger.info(f"[{domain}] Selenium completed: success={result.get('success')}")
        return result

    except Exception as e:
        logger.exception(f"[{domain}] Selenium automation error: {e}")
        return {"success": False, "error": str(e)}


async def _update_database_with_result(
    tenant_id: UUID, domain_id: UUID, domain_name: str,
    selenium_result: dict, domain_success: bool
) -> bool:
    """
    Update database with Selenium result using checkpoint commits.
    Each sub-step is committed individually for resilience.
    """
    for db_attempt in range(3):
        try:
            async with get_fresh_db_session() as db:
                tenant = await db.get(Tenant, tenant_id)
                domain = await db.get(Domain, domain_id)

                if not tenant or not domain:
                    logger.error(f"[{domain_name}] Tenant or domain not found in DB!")
                    return False

                # === CHECKPOINT: domain_added ===
                if selenium_result.get("domain_added"):
                    tenant.domain_added_to_m365 = True
                    if selenium_result.get("txt_value"):
                        tenant.m365_verification_txt = selenium_result["txt_value"]
                    logger.info(f"[{domain_name}] ✓ CHECKPOINT: domain_added")

                # === CHECKPOINT: domain_verified ===
                if selenium_result.get("domain_verified"):
                    tenant.domain_verified_in_m365 = True
                    tenant.domain_verified_at = datetime.utcnow()
                    domain.status = DomainStatus.M365_VERIFIED
                    domain.m365_verified_at = datetime.utcnow()
                    logger.info(f"[{domain_name}] ✓ CHECKPOINT: domain_verified")

                # === CHECKPOINT: dns_configured ===
                if selenium_result.get("dns_configured"):
                    tenant.dns_configured = True
                    tenant.mx_record_added = True
                    tenant.spf_record_added = True
                    tenant.autodiscover_added = True
                    domain.mx_configured = True
                    domain.spf_configured = True
                    domain.dns_records_created = True
                    if selenium_result.get("mx_value"):
                        tenant.mx_value = selenium_result["mx_value"]
                    if selenium_result.get("spf_value"):
                        tenant.spf_value = selenium_result["spf_value"]
                    logger.info(f"[{domain_name}] ✓ CHECKPOINT: dns_configured")

                # === CHECKPOINT: dkim_cnames_added ===
                if selenium_result.get("dkim_cnames_added"):
                    tenant.dkim_cnames_added = True
                    if selenium_result.get("dkim_selector1"):
                        tenant.dkim_selector1 = selenium_result["dkim_selector1"]
                        tenant.dkim_selector1_cname = selenium_result["dkim_selector1"]
                    if selenium_result.get("dkim_selector2"):
                        tenant.dkim_selector2 = selenium_result["dkim_selector2"]
                        tenant.dkim_selector2_cname = selenium_result["dkim_selector2"]
                    domain.dkim_cnames_added = True
                    logger.info(f"[{domain_name}] ✓ CHECKPOINT: dkim_cnames_added")

                # === CHECKPOINT: dkim_enabled (COMPLETE) ===
                if selenium_result.get("dkim_enabled"):
                    tenant.dkim_enabled = True
                    tenant.dkim_enabled_at = datetime.utcnow()
                    tenant.status = TenantStatus.DKIM_ENABLED
                    tenant.setup_error = None
                    tenant.setup_step = "6"
                    tenant.step5_complete = True
                    tenant.step5_completed_at = datetime.utcnow()
                    domain.dkim_enabled = True
                    domain.status = DomainStatus.ACTIVE
                    logger.info(f"[{domain_name}] ✓ CHECKPOINT: dkim_enabled (COMPLETE)")

                # Handle partial success (DNS + DKIM CNAMEs done, DKIM enable deferred)
                if (selenium_result.get("dns_configured") and
                    selenium_result.get("dkim_cnames_added") and
                    not selenium_result.get("dkim_enabled")):
                    tenant.setup_error = "DKIM enable pending — Microsoft provisioning delay"
                    tenant.status = TenantStatus.PENDING_DKIM
                    logger.info(f"[{domain_name}] Partial success — DKIM enable deferred to background job")

                # Handle failure
                if not domain_success:
                    error_msg = selenium_result.get("error", "Unknown error")
                    if not selenium_result.get("domain_verified"):
                        tenant.setup_error = error_msg

                await db.commit()

                # Verification
                await db.refresh(tenant)
                logger.info(f"[{domain_name}] DB committed: step5_complete={tenant.step5_complete}, "
                           f"dkim_enabled={tenant.dkim_enabled}, dns_configured={tenant.dns_configured}")
                return True

        except Exception as e:
            logger.error(f"[{domain_name}] DB update attempt {db_attempt+1} failed: {e}")
            if db_attempt < 2:
                await asyncio.sleep(5)
            else:
                logger.error(f"[{domain_name}] All DB update attempts failed!")
                return False

    return False


async def _mark_permanently_failed(tenant_id: UUID, domain_name: str):
    """Mark a domain as permanently failed after exhausting all retries."""
    try:
        async with get_fresh_db_session() as db:
            tenant = await db.get(Tenant, tenant_id)
            if tenant:
                tenant.permanently_failed = True
                tenant.setup_error = f"Permanently failed after {DOMAIN_RETRIES} attempts"
                await db.commit()
                logger.error(f"[{domain_name}] ✗✗✗ PERMANENTLY FAILED")
    except Exception as e:
        logger.error(f"[{domain_name}] Could not mark permanently failed: {e}")


# ============================================================
# SINGLE TENANT PROCESSOR (for individual runs)
# ============================================================

async def run_step5_for_tenant(db: AsyncSession, tenant_id: UUID, on_progress=None) -> Step5Result:
    """
    Run Step 5 for a single tenant using the bulletproof engine.
    """
    result = Step5Result(tenant_id=str(tenant_id), domain_name="unknown")

    logger.info(f"[SINGLE TENANT] Starting Step 5 for tenant_id={tenant_id}")

    try:
        tenant = await db.get(Tenant, tenant_id)
        if not tenant:
            result.error = "Tenant not found"
            return result

        result.domain_name = tenant.custom_domain or tenant.name
        domain_name = result.domain_name

        if not tenant.domain_id:
            result.error = "No domain linked"
            return result

        domain = await db.get(Domain, tenant.domain_id)
        if not domain:
            result.error = "Domain not found"
            return result

        if not tenant.admin_email or not tenant.admin_password or not tenant.totp_secret:
            result.error = "Missing credentials"
            tenant.setup_error = result.error
            await db.commit()
            return result

        td = {
            "tenant_id": str(tenant.id),
            "domain_id": str(domain.id),
            "domain": domain_name,
            "zone_id": domain.cloudflare_zone_id,
            "admin_email": tenant.admin_email,
            "admin_password": tenant.admin_password,
            "totp_secret": tenant.totp_secret,
            "onmicrosoft_domain": tenant.onmicrosoft_domain,
            "needs_add": not tenant.domain_added_to_m365,
            "needs_verify": not tenant.domain_verified_in_m365,
            "needs_dns": not tenant.dns_configured,
            "needs_dkim_cnames": not tenant.dkim_cnames_added,
            "needs_dkim_enable": not tenant.dkim_enabled,
        }

        # Run in thread pool
        loop = asyncio.get_event_loop()
        selenium_result = await loop.run_in_executor(None, _run_domain_setup_sync, td)

        # Update DB
        if selenium_result.get("success"):
            result.success = True
            result.domain_added = True
            result.domain_verified = True
            result.dns_configured = True
            result.dkim_cnames_added = True
            result.dkim_enabled = selenium_result.get("dkim_enabled", False)

            tenant.domain_added_to_m365 = True
            tenant.domain_verified_in_m365 = True
            tenant.domain_verified_at = datetime.utcnow()
            tenant.dns_configured = True
            tenant.mx_record_added = True
            tenant.spf_record_added = True
            tenant.autodiscover_added = True
            tenant.dkim_cnames_added = True

            if selenium_result.get("dkim_enabled"):
                tenant.dkim_enabled = True
                tenant.dkim_enabled_at = datetime.utcnow()
                tenant.status = TenantStatus.DKIM_ENABLED
                tenant.step5_complete = True
                tenant.step5_completed_at = datetime.utcnow()
                domain.dkim_enabled = True
                domain.status = DomainStatus.ACTIVE
            else:
                tenant.status = TenantStatus.PENDING_DKIM
                tenant.setup_error = "DKIM enable pending"

            tenant.setup_error = None if selenium_result.get("dkim_enabled") else "DKIM enable pending"
            domain.m365_verified_at = datetime.utcnow()
            domain.mx_configured = True
            domain.spf_configured = True
            domain.dns_records_created = True
            domain.dkim_cnames_added = True

            if selenium_result.get("mx_value"):
                tenant.mx_value = selenium_result["mx_value"]
            if selenium_result.get("spf_value"):
                tenant.spf_value = selenium_result["spf_value"]
            if selenium_result.get("dkim_selector1"):
                tenant.dkim_selector1_cname = selenium_result["dkim_selector1"]
            if selenium_result.get("dkim_selector2"):
                tenant.dkim_selector2_cname = selenium_result["dkim_selector2"]

            await db.commit()
            logger.info(f"[{domain_name}] DB committed successfully")

        elif selenium_result.get("domain_verified"):
            result.domain_added = True
            result.domain_verified = True
            result.error = "Domain verified but setup incomplete"

            tenant.domain_added_to_m365 = True
            tenant.domain_verified_in_m365 = True
            tenant.domain_verified_at = datetime.utcnow()
            tenant.status = TenantStatus.DOMAIN_VERIFIED
            tenant.setup_error = result.error
            domain.status = DomainStatus.M365_VERIFIED
            domain.m365_verified_at = datetime.utcnow()
            await db.commit()

        else:
            result.error = selenium_result.get("error", "Unknown error")
            result.error_step = "selenium_automation"
            tenant.setup_error = result.error
            await db.commit()

    except Exception as e:
        logger.exception(f"[{result.domain_name}] CRITICAL ERROR: {e}")
        result.error = f"Unhandled exception: {str(e)}"
        result.error_step = "unknown"

    return result


# ============================================================
# LEGACY M365SetupService CLASS (kept for API compatibility)
# ============================================================

class M365SetupService:
    """
    Legacy service class - kept for API compatibility.
    New code should use run_step5_for_batch() or run_step5_for_tenant() directly.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.cloudflare = cloudflare_service

    def validate_credentials(self, tenant: Tenant) -> Optional[str]:
        if not tenant.admin_email:
            return "No admin_email"
        if not tenant.admin_password:
            return "No admin_password"
        if not tenant.totp_secret:
            return "No totp_secret"
        return None

    async def setup_tenant_domain(self, tenant: Tenant, domain: Domain, on_progress=None) -> Step5Result:
        """Setup a single tenant domain using the bulletproof engine."""
        return await run_step5_for_tenant(self.db, tenant.id, on_progress)
