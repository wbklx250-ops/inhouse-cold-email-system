"""
M365 Setup Service - Automated Domain Verification & DKIM Setup

PARALLEL PROCESSING VERSION - Processes multiple domains simultaneously with staggered starts.

ARCHITECTURE NOTE (Asyncio Event Loop Fix):
============================================
This module carefully separates synchronous Selenium automation from async database operations:

1. SYNC SELENIUM: Runs in thread pool workers via ThreadPoolExecutor
   - _sync_setup_domain() - Pure synchronous function, NO async, NO database
   - Calls admin_portal.setup_domain_complete_via_admin_portal() which is synchronous
   
2. ASYNC DATABASE: Runs in main asyncio event loop
   - All SessionLocal() usage happens in main async context
   - Database updates happen as each thread completes, not inside threads
   
This prevents "Task got Future attached to a different loop" errors that occur
when async database sessions are used inside threaded code with separate event loops.
"""

import asyncio
import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import get_fresh_db_session
from app.models.tenant import Tenant, TenantStatus
from app.models.domain import Domain, DomainStatus
from app.services.cloudflare import cloudflare_service, CloudflareError

# Load settings from .env
_settings = get_settings()
MAX_PARALLEL_BROWSERS = _settings.max_parallel_browsers
STEP5_HEADLESS = _settings.step5_headless

logger = logging.getLogger(__name__)


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
            "dkim_config_retrieved": self.dkim_config_retrieved,
            "dkim_cnames_added": self.dkim_cnames_added,
            "dkim_enabled": self.dkim_enabled,
            "error": self.error, "error_step": self.error_step, "steps": self.steps
        }


# ============================================================
# SYNCHRONOUS SELENIUM WRAPPER
# This function runs in thread pool - NO async, NO database!
# ============================================================

def _sync_setup_domain(tenant_data: dict) -> dict:
    """
    Synchronous wrapper for domain setup via Selenium.
    
    CRITICAL: This function runs in a ThreadPoolExecutor thread.
    - NO async/await allowed
    - NO database operations allowed
    - NO asyncio event loop usage allowed
    
    Args:
        tenant_data: Dict containing:
            - domain: Domain name
            - zone_id: Cloudflare zone ID
            - admin_email: M365 admin email
            - admin_password: M365 admin password
            - totp_secret: TOTP secret for MFA
            - tenant_id: Tenant UUID (for logging only)
            - delay: Stagger delay in seconds
    
    Returns:
        Dict with automation results (success, verified, dns_configured, error)
    """
    domain = tenant_data["domain"]
    delay = tenant_data.get("delay", 0)
    
    # Apply stagger delay
    if delay > 0:
        logger.info(f"[{domain}] Waiting {delay}s before starting (stagger delay)...")
        time.sleep(delay)
    
    logger.info(f"[{domain}] Starting synchronous Selenium automation")
    
    try:
        # Import here to avoid circular imports and ensure fresh import per thread
        from app.services.selenium.admin_portal import setup_domain_with_retry
        
        # Call the SYNCHRONOUS Selenium function WITH RETRY
        result = setup_domain_with_retry(
            domain=domain,
            zone_id=tenant_data["zone_id"],
            admin_email=tenant_data["admin_email"],
            admin_password=tenant_data["admin_password"],
            totp_secret=tenant_data["totp_secret"],
            headless=STEP5_HEADLESS,
        )
        
        logger.info(f"[{domain}] Selenium automation completed: success={result.get('success')}")
        return result
        
    except Exception as e:
        logger.exception(f"[{domain}] Selenium automation error: {e}")
        return {
            "success": False,
            "verified": False,
            "dns_configured": False,
            "error": str(e)
        }


# ============================================================
# MAIN ASYNC BATCH PROCESSOR
# ============================================================

async def run_step5_for_batch(
    batch_id: UUID, on_progress=None
) -> Dict[str, Any]:
    """
    PARALLEL batch processing with proper async/sync separation.
    
    Architecture:
    1. ASYNC: Gather all tenant data from database (main event loop)
    2. SYNC IN THREADS: Run Selenium automation (thread pool, no async)
    3. ASYNC: Update database with results as each domain completes (main event loop)
    
    This prevents asyncio event loop conflicts between threads.
    """
    from app.models.batch import SetupBatch
    
    # ============ PARALLEL MODE INDICATOR ============
    logger.info("=" * 60)
    logger.info(f"=== PARALLEL MODE ACTIVE (ASYNC-SAFE) ===")
    logger.info(f"=== Processing up to {MAX_PARALLEL_BROWSERS} domains simultaneously ===")
    logger.info("=" * 60)
    
    # ============================================================
    # PHASE 1: GATHER TENANT DATA (Async, main event loop)
    # ============================================================
    
    logger.info("Phase 1: Gathering tenant data from database...")
    
    async with get_fresh_db_session() as db:
        result = await db.execute(
            select(Tenant).where(
                Tenant.batch_id == batch_id,
                Tenant.domain_id.isnot(None),
                Tenant.first_login_completed == True,
                Tenant.dkim_enabled != True
            )
        )
        tenants = list(result.scalars().all())
    
    summary = {"batch_id": str(batch_id), "total": len(tenants),
               "successful": 0, "failed": 0, "results": []}
    
    if not tenants:
        logger.info("No tenants to process")
        return summary
    
    # Prepare data for threads (extract all needed info, no SQLAlchemy objects)
    tenants_data = []
    tenant_lookup = {}  # Map domain -> tenant for DB updates later
    
    STAGGER_INTERVAL = 45  # Seconds between browser launches (increased from 15 to prevent resource exhaustion)
    
    for idx, tenant in enumerate(tenants):
        domain_name = tenant.custom_domain or tenant.name
        
        # Get domain info
        async with get_fresh_db_session() as db:
            domain = await db.get(Domain, tenant.domain_id)
        if not domain:
            logger.warning(f"[{domain_name}] Domain record not found, skipping")
            continue
        
        # Validate credentials
        if not tenant.admin_email or not tenant.admin_password or not tenant.totp_secret:
            logger.warning(f"[{domain_name}] Missing credentials, skipping")
            summary["results"].append({
                "tenant_id": str(tenant.id),
                "domain_name": domain_name,
                "success": False,
                "error": "Missing credentials (admin_email, admin_password, or totp_secret)"
            })
            summary["failed"] += 1
            continue
        
        # Check if already verified (skip Selenium, just do DKIM)
        already_verified = tenant.domain_verified_in_m365
        
        tenant_data = {
            "tenant_id": str(tenant.id),
            "domain_id": str(domain.id),
            "domain": domain_name,
            "zone_id": domain.cloudflare_zone_id,
            "admin_email": tenant.admin_email,
            "admin_password": tenant.admin_password,
            "totp_secret": tenant.totp_secret,
            "delay": idx * STAGGER_INTERVAL,
            "already_verified": already_verified,
        }
        
        tenants_data.append(tenant_data)
        tenant_lookup[domain_name] = {
            "tenant_id": tenant.id,
            "domain_id": domain.id
        }
        
        logger.info(f"Scheduled domain {idx+1}/{len(tenants)}: {domain_name} (starts in {idx * STAGGER_INTERVAL}s)")
    
    if not tenants_data:
        logger.info("No valid tenants to process after validation")
        return summary
    
    logger.info(f"Phase 1 complete: {len(tenants_data)} tenants ready for processing")
    
    # ============================================================
    # PHASE 2: RUN SELENIUM IN THREADS (Sync, thread pool)
    # ============================================================
    
    logger.info(f"Phase 2: Starting parallel Selenium automation with {MAX_PARALLEL_BROWSERS} workers...")
    
    loop = asyncio.get_event_loop()

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_BROWSERS) as executor:
        # Submit all tasks to thread pool using asyncio.gather() for reliable result mapping
        # NOTE: asyncio.gather() returns results in the SAME ORDER as input tasks
        tasks = [
            loop.run_in_executor(executor, _sync_setup_domain, td)
            for td in tenants_data
        ]
        
        logger.info(f"Waiting for {len(tasks)} Selenium tasks to complete...")
        
        # gather() with return_exceptions=True ensures all tasks complete even if some fail
        all_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        logger.info(f"All {len(all_results)} Selenium tasks completed, processing results...")

    # Process results - zip with tenants_data since gather() preserves order
    for tenant_data, selenium_result in zip(tenants_data, all_results):
        # CRITICAL FIX: Wrap ENTIRE iteration in try/except to prevent silent failures
        domain_name = tenant_data["domain"]
        try:
            tenant_id = UUID(tenant_data["tenant_id"])
            domain_id = UUID(tenant_data["domain_id"])
            
            logger.info(f"[{domain_name}] Processing Selenium result...")

            # Create Step5Result for summary
            step_result = Step5Result(
                tenant_id=str(tenant_id),
                domain_name=domain_name
            )

            # Handle exceptions returned by gather(return_exceptions=True)
            if isinstance(selenium_result, Exception):
                logger.error(f"[{domain_name}] Thread execution error: {selenium_result}")
                selenium_result = {
                    "success": False,
                    "verified": False,
                    "dns_configured": False,
                    "error": str(selenium_result)
                }
            else:
                logger.info(f"[{domain_name}] Selenium result received, success={selenium_result.get('success')}")
                if selenium_result.get("success"):
                    logger.info(f"[{domain_name}] Selenium automation SUCCESS - result: {selenium_result}")
                else:
                    logger.warning(f"[{domain_name}] Selenium automation FAILED: {selenium_result.get('error')}")

            # === ROBUST DB UPDATE WITH RETRY ===
            # CRITICAL: This block runs for ALL results (exceptions converted to dicts above)
            logger.info(f"[{domain_name}] >>> ENTERING DB UPDATE BLOCK <<<")
            
            # Use individual field updates with fresh sessions to avoid Neon timeouts
            db_update_success = False
            db_retry_count = 3
            
            for db_attempt in range(db_retry_count):
                try:
                    logger.info(f"[{domain_name}] DB update attempt {db_attempt + 1}/{db_retry_count} starting...")
                    
                    async with get_fresh_db_session() as db:
                        logger.info(f"[{domain_name}] Got fresh DB session, fetching tenant and domain...")
                        
                        # Re-fetch tenant and domain for updates (fresh from DB)
                        tenant = await db.get(Tenant, tenant_id)
                        domain = await db.get(Domain, domain_id)

                        if not tenant or not domain:
                            logger.error(f"[{domain_name}] CRITICAL: Tenant or domain not found! tenant={tenant}, domain={domain}")
                            step_result.error = "Tenant or domain not found in database"
                            step_result.error_step = "db_update"
                            summary["results"].append(step_result.to_dict())
                            summary["failed"] += 1
                            db_update_success = True  # Don't retry - entity missing
                            break

                        logger.info(f"[{domain_name}] Fetched tenant={tenant.name}, domain={domain.name}")

                        # Process Selenium result
                        if selenium_result.get("success"):
                            logger.info(f"[{domain_name}] Setting SUCCESS fields on tenant and domain...")
                            
                            # Full success - domain verified AND DNS configured
                            step_result.success = True
                            step_result.domain_added = True
                            step_result.domain_verified = True
                            step_result.txt_added_to_cloudflare = True
                            step_result.mail_dns_added = True
                            step_result.dkim_cnames_added = True
                            step_result.dkim_enabled = True

                            # Update tenant - all critical fields
                            tenant.domain_added_to_m365 = True
                            tenant.domain_verified_in_m365 = True
                            tenant.domain_verified_at = datetime.utcnow()
                            tenant.mx_record_added = True
                            tenant.spf_record_added = True
                            tenant.autodiscover_added = True
                            tenant.dkim_cnames_added = True
                            tenant.dkim_enabled = True
                            tenant.dkim_enabled_at = datetime.utcnow()
                            tenant.status = TenantStatus.DKIM_ENABLED
                            tenant.setup_error = None
                            tenant.setup_step = "6"  # Mark step 5 as complete
                            tenant.step5_complete = True
                            tenant.step5_completed_at = datetime.utcnow()
                            
                            # Store DNS values from Selenium result
                            if selenium_result.get("mx_value"):
                                tenant.mx_value = selenium_result["mx_value"]
                            if selenium_result.get("spf_value"):
                                tenant.spf_value = selenium_result["spf_value"]
                            if selenium_result.get("dkim_selector1_cname"):
                                tenant.dkim_selector1_cname = selenium_result["dkim_selector1_cname"]
                            if selenium_result.get("dkim_selector2_cname"):
                                tenant.dkim_selector2_cname = selenium_result["dkim_selector2_cname"]

                            # Update domain
                            domain.status = DomainStatus.ACTIVE
                            domain.m365_verified_at = datetime.utcnow()
                            domain.mx_configured = True
                            domain.spf_configured = True
                            domain.dns_records_created = True
                            domain.dkim_cnames_added = True
                            domain.dkim_enabled = True
                            
                            # Persist corrected zone_id if resolve_zone_id found a mismatch
                            if selenium_result.get("corrected_zone_id"):
                                old_zone_id = domain.cloudflare_zone_id
                                domain.cloudflare_zone_id = selenium_result["corrected_zone_id"]
                                logger.info(f"[{domain_name}] Updated cloudflare_zone_id: {old_zone_id} -> {selenium_result['corrected_zone_id']}")

                            logger.info(f"[{domain_name}] Fields set, calling db.commit()...")
                            await db.commit()
                            logger.info(f"[{domain_name}] db.commit() returned, verifying...")
                            
                            # VERIFICATION: Re-fetch to confirm save
                            await db.refresh(tenant)
                            logger.info(f"[{domain_name}] VERIFIED after commit: step5_complete={tenant.step5_complete}, dkim_enabled={tenant.dkim_enabled}")
                            
                            logger.info(f"[{domain_name}] [OK] DB COMMIT SUCCESS - step5_complete=True, dkim_enabled=True")

                            summary["successful"] += 1
                            db_update_success = True

                        elif selenium_result.get("verified"):
                            logger.info(f"[{domain_name}] Setting PARTIAL (verified only) fields...")
                            
                            # Partial success - domain verified but DNS may not be complete
                            step_result.domain_added = True
                            step_result.domain_verified = True

                            tenant.domain_added_to_m365 = True
                            tenant.domain_verified_in_m365 = True
                            tenant.domain_verified_at = datetime.utcnow()
                            tenant.status = TenantStatus.DOMAIN_VERIFIED
                            tenant.setup_error = "Domain verified but DNS setup incomplete"

                            domain.status = DomainStatus.M365_VERIFIED
                            domain.m365_verified_at = datetime.utcnow()

                            await db.commit()
                            logger.info(f"[{domain_name}] [OK] DB COMMIT SUCCESS - PARTIAL (verified only)")

                            # Mark as failed since not fully complete
                            step_result.error = "Domain verified but DNS setup incomplete"
                            step_result.error_step = "dns_setup"
                            summary["failed"] += 1
                            db_update_success = True

                        else:
                            logger.info(f"[{domain_name}] Setting FAILED state...")
                            
                            # Complete failure
                            error_msg = selenium_result.get("error", "Unknown error")
                            step_result.error = error_msg
                            step_result.error_step = "selenium_automation"

                            tenant.setup_error = error_msg
                            await db.commit()
                            logger.info(f"[{domain_name}] [FAIL] DB COMMIT SUCCESS - FAILED recorded: {error_msg}")

                            summary["failed"] += 1
                            db_update_success = True

                        summary["results"].append(step_result.to_dict())

                        # Progress callback
                        if on_progress:
                            on_progress(str(tenant_id), "complete", "success" if step_result.success else "failed")
                        
                        break  # Success - exit retry loop

                except Exception as e:
                    logger.error(f"[{domain_name}] DB update attempt {db_attempt + 1} FAILED: {e}")
                    logger.exception(f"[{domain_name}] Full traceback for DB error:")
                    if db_attempt < db_retry_count - 1:
                        logger.info(f"[{domain_name}] Retrying DB update in 5 seconds...")
                        await asyncio.sleep(5)
                    else:
                        logger.exception(f"[{domain_name}] All {db_retry_count} DB update attempts failed!")
                        step_result.error = f"Database update failed after {db_retry_count} attempts: {str(e)}"
                        step_result.error_step = "db_update"
                        summary["results"].append(step_result.to_dict())
                        summary["failed"] += 1
            
            logger.info(f"[{domain_name}] >>> EXITING DB UPDATE BLOCK, success={db_update_success} <<<")
                
        except Exception as outer_e:
            # CRITICAL: Catch ANY unhandled exception in the loop iteration
            logger.exception(f"[{domain_name}] CRITICAL UNHANDLED ERROR in Step 5 loop iteration: {outer_e}")
            logger.error(f"[{domain_name}] This error prevented DB persistence - continuing to next tenant")
            summary["failed"] += 1
            # Continue to next tenant instead of crashing entire batch
            continue

    logger.info("Phase 2 complete: All Selenium tasks finished")
    
    # ============================================================
    # PHASE 4: UPDATE BATCH STATUS
    # ============================================================
    
    logger.info("Phase 4: Updating batch status...")
    
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
    
    logger.info("=" * 60)
    logger.info(f"=== STEP 5 COMPLETE: {summary['successful']}/{summary['total']} successful ===")
    logger.info("=" * 60)
    
    return summary


# ============================================================
# SINGLE TENANT PROCESSOR (for individual runs)
# ============================================================

async def run_step5_for_tenant(db: AsyncSession, tenant_id: UUID, on_progress=None) -> Step5Result:
    """
    Run Step 5 for a single tenant.
    
    Uses the same async-safe pattern as batch processing.
    """
    result = Step5Result(tenant_id=str(tenant_id), domain_name="unknown")
    
    logger.info(f"[SINGLE TENANT] Starting Step 5 for tenant_id={tenant_id}")
    
    try:
        # PHASE 1: Gather data
        tenant = await db.get(Tenant, tenant_id)
        if not tenant:
            result.error = "Tenant not found"
            result.error_step = "lookup"
            logger.error(f"[SINGLE TENANT] Tenant {tenant_id} not found")
            return result
        
        result.domain_name = tenant.custom_domain or tenant.name
        logger.info(f"[{result.domain_name}] Found tenant: {tenant.name}")
        
        if not tenant.domain_id:
            result.error = "No domain linked"
            result.error_step = "lookup"
            logger.error(f"[{result.domain_name}] No domain linked")
            return result
        
        domain = await db.get(Domain, tenant.domain_id)
        if not domain:
            result.error = "Domain not found"
            result.error_step = "lookup"
            logger.error(f"[{result.domain_name}] Domain {tenant.domain_id} not found")
            return result
        
        # Validate credentials
        if not tenant.admin_email or not tenant.admin_password or not tenant.totp_secret:
            result.error = "Missing credentials"
            result.error_step = "credential_check"
            tenant.setup_error = result.error
            await db.commit()
            logger.error(f"[{result.domain_name}] Missing credentials")
            return result
        
        tenant_data = {
            "tenant_id": str(tenant.id),
            "domain_id": str(domain.id),
            "domain": result.domain_name,
            "zone_id": domain.cloudflare_zone_id,
            "admin_email": tenant.admin_email,
            "admin_password": tenant.admin_password,
            "totp_secret": tenant.totp_secret,
            "delay": 0,  # No stagger for single tenant
        }
        
        # PHASE 2: Run Selenium in thread
        logger.info(f"[{result.domain_name}] Starting Selenium automation...")
        loop = asyncio.get_event_loop()
        selenium_result = await loop.run_in_executor(None, _sync_setup_domain, tenant_data)
        logger.info(f"[{result.domain_name}] Selenium result: {selenium_result}")
        
        # PHASE 3: Update database
        logger.info(f"[{result.domain_name}] >>> ENTERING DB UPDATE BLOCK <<<")
        
        if selenium_result.get("success"):
            logger.info(f"[{result.domain_name}] Setting SUCCESS fields...")
            
            result.success = True
            result.domain_added = True
            result.domain_verified = True
            result.txt_added_to_cloudflare = True
            result.mail_dns_added = True
            result.dkim_cnames_added = True
            result.dkim_enabled = True
            
            tenant.domain_added_to_m365 = True
            tenant.domain_verified_in_m365 = True
            tenant.domain_verified_at = datetime.utcnow()
            tenant.mx_record_added = True
            tenant.spf_record_added = True
            tenant.autodiscover_added = True
            tenant.dkim_cnames_added = True
            tenant.dkim_enabled = True
            tenant.dkim_enabled_at = datetime.utcnow()
            tenant.status = TenantStatus.DKIM_ENABLED
            tenant.setup_error = None
            tenant.step5_complete = True
            tenant.step5_completed_at = datetime.utcnow()
            
            # Store DNS values from Selenium result
            if selenium_result.get("mx_value"):
                tenant.mx_value = selenium_result["mx_value"]
            if selenium_result.get("spf_value"):
                tenant.spf_value = selenium_result["spf_value"]
            if selenium_result.get("dkim_selector1_cname"):
                tenant.dkim_selector1_cname = selenium_result["dkim_selector1_cname"]
            if selenium_result.get("dkim_selector2_cname"):
                tenant.dkim_selector2_cname = selenium_result["dkim_selector2_cname"]
            
            domain.status = DomainStatus.ACTIVE
            domain.m365_verified_at = datetime.utcnow()
            domain.mx_configured = True
            domain.spf_configured = True
            domain.dns_records_created = True
            domain.dkim_cnames_added = True
            domain.dkim_enabled = True
            
            # Persist corrected zone_id if resolve_zone_id found a mismatch
            if selenium_result.get("corrected_zone_id"):
                old_zone_id = domain.cloudflare_zone_id
                domain.cloudflare_zone_id = selenium_result["corrected_zone_id"]
                logger.info(f"[{result.domain_name}] Updated cloudflare_zone_id: {old_zone_id} -> {selenium_result['corrected_zone_id']}")
            
            logger.info(f"[{result.domain_name}] Calling db.commit()...")
            await db.commit()
            
            # VERIFICATION: Re-fetch to confirm save
            await db.refresh(tenant)
            logger.info(f"[{result.domain_name}] VERIFIED after commit: step5_complete={tenant.step5_complete}, dkim_enabled={tenant.dkim_enabled}")
            logger.info(f"[{result.domain_name}] [OK] DB COMMIT SUCCESS - step5_complete=True, dkim_enabled=True")
            
        elif selenium_result.get("verified"):
            logger.info(f"[{result.domain_name}] Setting PARTIAL (verified only) fields...")
            
            result.domain_added = True
            result.domain_verified = True
            result.error = "Domain verified but DNS setup incomplete"
            result.error_step = "dns_setup"
            
            tenant.domain_added_to_m365 = True
            tenant.domain_verified_in_m365 = True
            tenant.domain_verified_at = datetime.utcnow()
            tenant.status = TenantStatus.DOMAIN_VERIFIED
            tenant.setup_error = result.error
            
            domain.status = DomainStatus.M365_VERIFIED
            domain.m365_verified_at = datetime.utcnow()
            
            await db.commit()
            logger.info(f"[{result.domain_name}] [OK] DB COMMIT SUCCESS - PARTIAL (verified only)")
            
        else:
            logger.info(f"[{result.domain_name}] Setting FAILED state...")
            
            result.error = selenium_result.get("error", "Unknown error")
            result.error_step = "selenium_automation"
            tenant.setup_error = result.error
            await db.commit()
            logger.info(f"[{result.domain_name}] [FAIL] DB COMMIT SUCCESS - FAILED recorded: {result.error}")
        
        logger.info(f"[{result.domain_name}] >>> EXITING DB UPDATE BLOCK <<<")
        
    except Exception as e:
        logger.exception(f"[{result.domain_name}] CRITICAL ERROR in run_step5_for_tenant: {e}")
        result.error = f"Unhandled exception: {str(e)}"
        result.error_step = "unknown"
    
    return result


# ============================================================
# LEGACY M365SetupService CLASS (kept for compatibility)
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
        """Setup a single tenant domain using the new async-safe pattern."""
        return await run_step5_for_tenant(self.db, tenant.id, on_progress)
