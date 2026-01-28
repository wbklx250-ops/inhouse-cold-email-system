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
   - Database updates happen AFTER threads complete, not inside threads
   
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
    TRUE BATCH PROCESSING - Process domains in chunks of 3.
    
    Memory-efficient architecture:
    - Only gather data for the current chunk (3 domains)
    - Process that chunk completely (Selenium + DB updates)
    - Then move to next chunk
    
    This prevents memory issues when processing 50+ domains by NOT
    pre-scheduling all domains upfront.
    """
    from app.models.batch import SetupBatch
    
    # ============ TRUE BATCH MODE INDICATOR ============
    logger.info("=" * 60)
    logger.info(f"=== TRUE BATCH MODE (MEMORY EFFICIENT) ===")
    logger.info(f"=== Processing in chunks of 3, max {MAX_PARALLEL_BROWSERS} parallel browsers ===")
    logger.info("=" * 60)
    
    CHUNK_SIZE = 3
    STAGGER_INTERVAL = 15  # Seconds between browser launches within a chunk
    
    # ============================================================
    # INITIAL: Get list of tenant IDs to process (lightweight query)
    # ============================================================
    
    logger.info("Getting list of tenants to process...")
    
    async with get_fresh_db_session() as db:
        result = await db.execute(
            select(Tenant.id, Tenant.custom_domain, Tenant.name).where(
                Tenant.batch_id == batch_id,
                Tenant.domain_id.isnot(None),
                Tenant.first_login_completed == True,
                Tenant.dkim_enabled != True
            )
        )
        tenant_refs = list(result.all())  # List of (id, custom_domain, name) tuples
    
    total_tenants = len(tenant_refs)
    summary = {"batch_id": str(batch_id), "total": total_tenants,
               "successful": 0, "failed": 0, "results": []}
    
    if not tenant_refs:
        logger.info("No tenants to process")
        return summary
    
    logger.info(f"Found {total_tenants} tenants to process in chunks of {CHUNK_SIZE}")
    
    total_chunks = (total_tenants + CHUNK_SIZE - 1) // CHUNK_SIZE
    loop = asyncio.get_event_loop()
    
    # ============================================================
    # PROCESS IN TRUE CHUNKS - Gather, Process, Update per chunk
    # ============================================================
    
    for chunk_start in range(0, total_tenants, CHUNK_SIZE):
        chunk_refs = tenant_refs[chunk_start:chunk_start + CHUNK_SIZE]
        chunk_num = (chunk_start // CHUNK_SIZE) + 1
        
        logger.info("=" * 40)
        logger.info(f"CHUNK {chunk_num}/{total_chunks}: Processing {len(chunk_refs)} domains")
        logger.info("=" * 40)
        
        # ========== PHASE 1: Gather data for THIS CHUNK ONLY ==========
        
        chunk_data = []
        chunk_lookup = {}  # Map domain -> tenant for DB updates
        
        for idx, (tenant_id, custom_domain, tenant_name) in enumerate(chunk_refs):
            domain_name = custom_domain or tenant_name
            
            # Get full tenant and domain info
            async with get_fresh_db_session() as db:
                tenant = await db.get(Tenant, tenant_id)
                if not tenant:
                    logger.warning(f"[{domain_name}] Tenant not found, skipping")
                    summary["failed"] += 1
                    summary["results"].append({
                        "tenant_id": str(tenant_id),
                        "domain_name": domain_name,
                        "success": False,
                        "error": "Tenant not found"
                    })
                    continue
                
                domain = await db.get(Domain, tenant.domain_id)
                if not domain:
                    logger.warning(f"[{domain_name}] Domain record not found, skipping")
                    summary["failed"] += 1
                    summary["results"].append({
                        "tenant_id": str(tenant_id),
                        "domain_name": domain_name,
                        "success": False,
                        "error": "Domain record not found"
                    })
                    continue
                
                # Validate credentials
                if not tenant.admin_email or not tenant.admin_password or not tenant.totp_secret:
                    logger.warning(f"[{domain_name}] Missing credentials, skipping")
                    summary["failed"] += 1
                    summary["results"].append({
                        "tenant_id": str(tenant_id),
                        "domain_name": domain_name,
                        "success": False,
                        "error": "Missing credentials (admin_email, admin_password, or totp_secret)"
                    })
                    continue
                
                # Build tenant data for Selenium (within-chunk delay)
                tenant_data = {
                    "tenant_id": str(tenant.id),
                    "domain_id": str(domain.id),
                    "domain": domain_name,
                    "zone_id": domain.cloudflare_zone_id,
                    "admin_email": tenant.admin_email,
                    "admin_password": tenant.admin_password,
                    "totp_secret": tenant.totp_secret,
                    "delay": idx * STAGGER_INTERVAL,  # Within-chunk delay: 0, 15, 30
                    "already_verified": tenant.domain_verified_in_m365,
                }
                
                chunk_data.append(tenant_data)
                chunk_lookup[domain_name] = {
                    "tenant_id": tenant.id,
                    "domain_id": domain.id
                }
                
                logger.info(f"  [{chunk_num}.{idx+1}] {domain_name} (delay: {idx * STAGGER_INTERVAL}s)")
        
        if not chunk_data:
            logger.info(f"Chunk {chunk_num}: No valid tenants after validation, moving to next chunk")
            continue
        
        # ========== PHASE 2: Run Selenium for THIS CHUNK ==========
        
        logger.info(f"Chunk {chunk_num}: Starting Selenium for {len(chunk_data)} domains...")
        
        chunk_results = {}  # domain -> result dict
        
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_BROWSERS) as executor:
            future_to_domain = {}
            
            for tenant_data in chunk_data:
                domain_name = tenant_data["domain"]
                
                future = loop.run_in_executor(
                    executor,
                    _sync_setup_domain,
                    tenant_data
                )
                future_to_domain[future] = {
                    "domain": domain_name,
                    "tenant_data": tenant_data
                }
            
            # Wait for all tasks in this chunk to complete
            for future in asyncio.as_completed(list(future_to_domain.keys())):
                task_info = future_to_domain[future]
                domain_name = task_info["domain"]
                
                try:
                    result = await future
                    chunk_results[domain_name] = result
                    
                    if result.get("success"):
                        logger.info(f"[{domain_name}] SUCCESS")
                    else:
                        logger.warning(f"[{domain_name}] FAILED: {result.get('error')}")
                
                except Exception as e:
                    logger.exception(f"[{domain_name}] Thread error: {e}")
                    chunk_results[domain_name] = {
                        "success": False,
                        "verified": False,
                        "dns_configured": False,
                        "error": str(e)
                    }
        
        # ========== PHASE 3: Update database for THIS CHUNK ==========
        
        logger.info(f"Chunk {chunk_num}: Updating database...")
        
        for domain_name, selenium_result in chunk_results.items():
            lookup = chunk_lookup.get(domain_name)
            if not lookup:
                continue
            
            tenant_id = lookup["tenant_id"]
            domain_id = lookup["domain_id"]
            
            step_result = Step5Result(
                tenant_id=str(tenant_id),
                domain_name=domain_name
            )
            
            try:
                async with get_fresh_db_session() as db:
                    tenant = await db.get(Tenant, tenant_id)
                    domain = await db.get(Domain, domain_id)
                    
                    if not tenant or not domain:
                        step_result.error = "Tenant or domain not found"
                        step_result.error_step = "db_update"
                        summary["results"].append(step_result.to_dict())
                        summary["failed"] += 1
                        continue
                    
                    if selenium_result.get("success") and selenium_result.get("dns_configured"):
                        # Full success
                        step_result.success = True
                        step_result.domain_added = True
                        step_result.domain_verified = True
                        step_result.txt_added_to_cloudflare = True
                        step_result.mail_dns_added = True
                        step_result.dkim_cnames_added = True
                        step_result.dkim_enabled = True
                        
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
                        tenant.setup_step = 6
                        
                        domain.status = DomainStatus.ACTIVE
                        domain.m365_verified_at = datetime.utcnow()
                        domain.mx_configured = True
                        domain.spf_configured = True
                        domain.dns_records_created = True
                        domain.dkim_cnames_added = True
                        domain.dkim_enabled = True
                        
                        await db.commit()
                        summary["successful"] += 1
                        logger.info(f"[{domain_name}] DB: FULL SUCCESS")
                        
                    elif selenium_result.get("verified"):
                        # Partial success
                        step_result.domain_added = True
                        step_result.domain_verified = True
                        step_result.error = "Domain verified but DNS setup incomplete"
                        step_result.error_step = "dns_setup"
                        
                        tenant.domain_added_to_m365 = True
                        tenant.domain_verified_in_m365 = True
                        tenant.domain_verified_at = datetime.utcnow()
                        tenant.status = TenantStatus.DOMAIN_VERIFIED
                        tenant.setup_error = "DNS setup incomplete"
                        
                        domain.status = DomainStatus.M365_VERIFIED
                        domain.m365_verified_at = datetime.utcnow()
                        
                        await db.commit()
                        summary["failed"] += 1
                        logger.warning(f"[{domain_name}] DB: PARTIAL")
                        
                    else:
                        # Complete failure
                        error_msg = selenium_result.get("error", "Unknown error")
                        step_result.error = error_msg
                        step_result.error_step = "selenium_automation"
                        
                        tenant.setup_error = error_msg
                        await db.commit()
                        
                        summary["failed"] += 1
                        logger.error(f"[{domain_name}] DB: FAILED - {error_msg}")
                    
                    summary["results"].append(step_result.to_dict())
                    
                    if on_progress:
                        on_progress(str(tenant_id), "complete", "success" if step_result.success else "failed")
                        
            except Exception as e:
                logger.exception(f"[{domain_name}] DB update error: {e}")
                step_result.error = f"Database error: {str(e)}"
                step_result.error_step = "db_update"
                summary["results"].append(step_result.to_dict())
                summary["failed"] += 1
        
        logger.info(f"Chunk {chunk_num}/{total_chunks} complete")
        
        # Brief pause between chunks
        if chunk_start + CHUNK_SIZE < total_tenants:
            logger.info("Pausing 2s before next chunk...")
            await asyncio.sleep(2)
    
    # ============================================================
    # FINAL: Update batch status
    # ============================================================
    
    logger.info("Updating batch status...")
    
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
    
    # PHASE 1: Gather data
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        result.error = "Tenant not found"
        result.error_step = "lookup"
        return result
    
    result.domain_name = tenant.custom_domain or tenant.name
    
    if not tenant.domain_id:
        result.error = "No domain linked"
        result.error_step = "lookup"
        return result
    
    domain = await db.get(Domain, tenant.domain_id)
    if not domain:
        result.error = "Domain not found"
        result.error_step = "lookup"
        return result
    
    # Validate credentials
    if not tenant.admin_email or not tenant.admin_password or not tenant.totp_secret:
        result.error = "Missing credentials"
        result.error_step = "credential_check"
        tenant.setup_error = result.error
        await db.commit()
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
    loop = asyncio.get_event_loop()
    selenium_result = await loop.run_in_executor(None, _sync_setup_domain, tenant_data)
    
    # PHASE 3: Update database
    if selenium_result.get("success") and selenium_result.get("dns_configured"):
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
        
        domain.status = DomainStatus.ACTIVE
        domain.m365_verified_at = datetime.utcnow()
        domain.mx_configured = True
        domain.spf_configured = True
        domain.dns_records_created = True
        domain.dkim_cnames_added = True
        domain.dkim_enabled = True
        
        await db.commit()
        
    elif selenium_result.get("verified"):
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
        
    else:
        result.error = selenium_result.get("error", "Unknown error")
        result.error_step = "selenium_automation"
        tenant.setup_error = result.error
        await db.commit()
    
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
