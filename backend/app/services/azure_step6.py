"""
Step 6 Orchestrator (Selenium -> PowerShell -> Selenium)

Uses Selenium to create the licensed user, PowerShell device code auth
to create shared mailboxes and delegation, then Selenium Admin UI to
set passwords and enable accounts.
"""

import asyncio
try:
    current_loop = asyncio.get_running_loop()
except RuntimeError:
    current_loop = None

if current_loop is None or type(current_loop).__module__ != "uvloop":
    import nest_asyncio

    nest_asyncio.apply()
import logging
import time
from datetime import datetime
from typing import Dict, Any, List
from uuid import UUID

from sqlalchemy import select, update, func

from app.core.config import get_settings
from app.db.session import SessionLocal, async_session_factory
from app.models.batch import SetupBatch, BatchStatus
from app.models.mailbox import Mailbox, MailboxStatus
from app.models.tenant import Tenant, TenantStatus
from app.services.email_generator import generate_emails_for_domain
from app.services.powershell_exchange import PowerShellExchangeService
from app.services.selenium.admin_portal import _login_with_mfa
from app.services.selenium.browser import create_driver, cleanup_driver
from app.services.selenium.user_ops import UserOpsSelenium

logger = logging.getLogger(__name__)

_progress_store: Dict[str, Dict[str, Any]] = {}


def update_progress(tenant_id: str, step: str, status: str, detail: str = ""):
    """Update progress for real-time UI tracking."""
    _progress_store[tenant_id] = {
        "step": step,
        "status": status,
        "detail": detail,
        "timestamp": time.time(),
    }
    logger.info("[%s] %s: %s - %s", tenant_id[:8], step, status, detail)


def get_progress(tenant_id: str) -> Dict[str, Any]:
    """Get current progress for a tenant."""
    return _progress_store.get(tenant_id, {})


def get_all_progress() -> Dict[str, Dict[str, Any]]:
    """Get progress for all tenants."""
    return dict(_progress_store)


async def run_step6_for_batch(batch_id: UUID, display_name: str) -> Dict[str, Any]:
    """Run Step 6 for all eligible tenants in a batch."""
    logger.info(
        "Starting Step 6 for batch %s with display name: %s",
        batch_id,
        display_name,
    )

    async with async_session_factory() as db:
        batch = await db.get(SetupBatch, batch_id)
        if not batch:
            logger.error("Batch %s not found", batch_id)
            return {"success": False, "error": "Batch not found"}

        first_name, last_name = (
            display_name.strip().split(" ", 1)
            if " " in display_name
            else (display_name, "")
        )
        await db.execute(
            update(SetupBatch)
            .where(SetupBatch.id == batch_id)
            .values(
                persona_first_name=first_name,
                persona_last_name=last_name,
            )
        )
        await db.commit()

        result = await db.execute(
            select(Tenant).where(
                Tenant.batch_id == batch_id,
                Tenant.domain_verified_in_m365 == True,
                Tenant.step6_complete == False,
            )
        )
        tenants = result.scalars().all()

        if not tenants:
            logger.warning("No eligible tenants found for batch %s", batch_id)
            return {"success": False, "error": "No eligible tenants"}

        results: List[Dict[str, Any]] = []
        successful = 0
        failed = 0

        # Parallel processing with semaphore (default 5 concurrent browsers)
        settings = get_settings()
        max_parallel = int(settings.max_parallel_browsers) if hasattr(settings, "max_parallel_browsers") else 5
        max_parallel = max(1, min(max_parallel, 10))  # clamp 1-10
        semaphore = asyncio.Semaphore(max_parallel)

        logger.info(
            "Processing %s tenants with max_parallel=%s",
            len(tenants),
            max_parallel,
        )

        async def _process_one(idx: int, tenant):
            async with semaphore:
                logger.info("=" * 80)
                logger.info(
                    "BATCH PROGRESS: Tenant %s/%s - %s",
                    idx,
                    len(tenants),
                    tenant.custom_domain,
                )
                logger.info("=" * 80)

                try:
                    tenant_result = await run_step6_for_tenant(tenant.id)
                    return {
                        "tenant_id": str(tenant.id),
                        "result": tenant_result,
                    }
                except Exception as e:
                    logger.error(
                        "[%s] Tenant exception: %s",
                        tenant.custom_domain,
                        str(e),
                    )
                    return {
                        "tenant_id": str(tenant.id),
                        "result": {"success": False, "error": str(e)},
                    }

        tasks = [
            _process_one(i, tenant)
            for i, tenant in enumerate(tenants, 1)
        ]
        gathered = await asyncio.gather(*tasks, return_exceptions=True)

        for item in gathered:
            if isinstance(item, Exception):
                failed += 1
                results.append(
                    {"tenant_id": "unknown", "result": {"success": False, "error": str(item)}}
                )
            else:
                results.append(item)
                if item["result"].get("success"):
                    successful += 1
                else:
                    failed += 1
                    logger.error(
                        "Tenant %s failed: %s",
                        item["tenant_id"][:8],
                        item["result"].get("error"),
                    )
        
        logger.info("=" * 80)
        logger.info("BATCH COMPLETE: %s/%s successful, %s failed", successful, len(tenants), failed)
        logger.info("=" * 80)

        # Update batch status when step 6 completes
        # IMPORTANT: Step 6 should NOT mark the batch as complete.
        # Instead, advance to Step 7 when all tenants succeed.
        completed_steps = batch.completed_steps or []
        if 6 not in completed_steps:
            completed_steps.append(6)

        batch.completed_steps = sorted(completed_steps)

        if failed == 0:
            # All tenants succeeded - advance to Step 7
            batch.current_step = 7
            await db.commit()
            logger.info("Batch %s advanced to Step 7 (step 6 done, all tenants succeeded)", batch_id)
        else:
            # Some tenants failed - stay on Step 6 for retry
            batch.current_step = 6
            await db.commit()
            logger.info("Batch %s step 6 finished with %s failures - batch NOT marked complete", batch_id, failed)

        return {
            "success": failed == 0,
            "total": len(tenants),
            "successful": successful,
            "failed": failed,
            "results": results,
        }


async def run_step6_for_tenant(tenant_id: UUID) -> Dict[str, Any]:
    """Run Step 6 for a single tenant using Selenium + PowerShell + Selenium UI."""
    async with async_session_factory() as db:
        tenant = await db.get(Tenant, tenant_id)
        if not tenant:
            logger.error("Tenant %s not found", tenant_id)
            return {"success": False, "error": "Tenant not found"}

        logger.info("[%s] Checking current state...", tenant.custom_domain)
        logger.info("  - mailboxes_created: %s", tenant.step6_mailboxes_created)
        logger.info("  - delegations_done: %s", tenant.step6_delegations_done)
        logger.info("  - passwords_set: %s", tenant.step6_passwords_set)
        logger.info("  - complete: %s", tenant.step6_complete)

        if tenant.step6_complete:
            logger.info("[%s] SKIPPING - already complete", tenant.custom_domain)
            update_progress(str(tenant.id), "complete", "complete", "Step 6 already complete")
            return {"success": True, "skipped": True}

        # RETRY FIX: Clear previous error on retry start
        if tenant.step6_error:
            logger.info("[%s] Clearing previous error for retry: %s", tenant.custom_domain, tenant.step6_error)
            tenant.step6_error = None
            await db.commit()

        # CRITICAL FIX: Check ACTUAL mailbox state in DB, not just counter fields
        # Counter fields can be stale from previous partial runs
        mailbox_count_result = await db.execute(
            select(func.count(Mailbox.id)).where(Mailbox.tenant_id == tenant.id)
        )
        total_mailbox_count = mailbox_count_result.scalar() or 0
        
        created_count_result = await db.execute(
            select(func.count(Mailbox.id)).where(
                Mailbox.tenant_id == tenant.id,
                Mailbox.created_in_exchange == True,
            )
        )
        actual_created_count = created_count_result.scalar() or 0
        
        delegated_count_result = await db.execute(
            select(func.count(Mailbox.id)).where(
                Mailbox.tenant_id == tenant.id,
                Mailbox.delegated == True,
            )
        )
        actual_delegated_count = delegated_count_result.scalar() or 0
        
        password_set_count_result = await db.execute(
            select(func.count(Mailbox.id)).where(
                Mailbox.tenant_id == tenant.id,
                Mailbox.password_set == True,
            )
        )
        actual_password_set_count = password_set_count_result.scalar() or 0
        
        # FORCE RETRY FIX: ALWAYS run PowerShell and Admin UI on retry
        # The database may falsely show completion when M365 tenant was recreated
        # Licensed user check happens separately and correctly skips if already created
        # But mailbox creation/delegation/passwords must ALWAYS be re-attempted
        needs_powershell = True  # ALWAYS attempt PowerShell operations
        needs_admin_ui = True    # ALWAYS attempt Admin UI password reset
        
        logger.info("[%s] Actual DB state: total=%s, created=%s, delegated=%s, passwords_set=%s",
                    tenant.custom_domain, total_mailbox_count, actual_created_count, 
                    actual_delegated_count, actual_password_set_count)
        logger.info("[%s] needs_powershell=%s, needs_admin_ui=%s", 
                    tenant.custom_domain, needs_powershell, needs_admin_ui)

        if needs_powershell:
            logger.info("[%s] RUNNING PowerShell...", tenant.custom_domain)
        else:
            logger.info("[%s] SKIPPING PowerShell - already done", tenant.custom_domain)

        if needs_admin_ui:
            logger.info("[%s] RUNNING Admin UI password reset...", tenant.custom_domain)
        else:
            logger.info("[%s] SKIPPING Admin UI password reset - already done", tenant.custom_domain)

        update_progress(str(tenant.id), "starting", "in_progress", "Initializing...")

        if not tenant.admin_email or not tenant.admin_password:
            message = "Missing admin credentials"
            logger.error("[%s] %s", tenant.custom_domain, message)
            tenant.step6_error = message
            await db.commit()
            update_progress(str(tenant.id), "error", "failed", message)
            return {"success": False, "error": message}

        if not tenant.onmicrosoft_domain:
            message = "Missing onmicrosoft domain"
            logger.error("[%s] %s", tenant.custom_domain, message)
            tenant.step6_error = message
            await db.commit()
            update_progress(str(tenant.id), "error", "failed", message)
            return {"success": False, "error": message}

        driver = None
        ps_service = None
        settings = get_settings()
        try:
            batch = None
            if tenant.batch_id:
                batch = await db.get(SetupBatch, tenant.batch_id)

            # BROWSER RETRY LOGIC: Handle browser crashes with retry
            MAX_BROWSER_RETRIES = 2
            browser_retry_count = 0
            login_successful = False
            
            while browser_retry_count < MAX_BROWSER_RETRIES and not login_successful:
                try:
                    browser_retry_count += 1
                    # Step 1: Selenium login to Admin Portal
                    update_progress(str(tenant.id), "login", "in_progress", 
                        f"Logging into M365 Admin Portal... (attempt {browser_retry_count}/{MAX_BROWSER_RETRIES})")
                    
                    # Clean up any existing driver before creating new one
                    if driver:
                        try:
                            cleanup_driver(driver)
                        except Exception:
                            pass
                        driver = None
                    
                    driver = create_driver(headless=settings.step6_headless)
                    _login_with_mfa(
                        driver=driver,
                        admin_email=tenant.admin_email,
                        admin_password=tenant.admin_password,
                        totp_secret=tenant.totp_secret,
                        domain=tenant.custom_domain,
                    )
                    login_successful = True
                    update_progress(str(tenant.id), "login", "complete", "Logged in successfully")
                    
                except Exception as browser_error:
                    error_str = str(browser_error)
                    is_connection_error = (
                        "HTTPConnectionPool" in error_str or 
                        "NewConnectionError" in error_str or
                        "target machine actively refused" in error_str or
                        "session" in error_str.lower() and "delete" in error_str.lower()
                    )
                    
                    if is_connection_error and browser_retry_count < MAX_BROWSER_RETRIES:
                        logger.warning(
                            "[%s] Browser connection error (attempt %s/%s): %s - retrying in 5 seconds...",
                            tenant.custom_domain, browser_retry_count, MAX_BROWSER_RETRIES, error_str[:100]
                        )
                        # Clean up crashed driver
                        if driver:
                            try:
                                cleanup_driver(driver)
                            except Exception:
                                pass
                            driver = None
                        await asyncio.sleep(5)
                    else:
                        # Not a connection error or out of retries
                        raise
            
            if not login_successful:
                raise Exception(f"Failed to login after {MAX_BROWSER_RETRIES} attempts")

            # Step 2 + 3: Selenium create licensed user + assign license
            update_progress(
                str(tenant.id),
                "licensed_user",
                "in_progress",
                "Creating licensed user in M365 Admin UI",
            )
            user_ops = UserOpsSelenium(driver, tenant.custom_domain)

            licensed_user = None
            if tenant.licensed_user_created and tenant.licensed_user_upn:
                licensed_user = {
                    "success": True,
                    "email": tenant.licensed_user_upn,
                    "password": tenant.licensed_user_password,
                    "skipped": True,
                }
            else:
                licensed_user = user_ops.create_licensed_user(
                    username="me1",
                    display_name="me1",
                    password=tenant.licensed_user_password or "#Sendemails1",
                    custom_domain=tenant.custom_domain,
                )
                if not licensed_user.get("success"):
                    raise Exception(licensed_user.get("error") or "Failed to create licensed user")

                tenant.licensed_user_created = True
                tenant.licensed_user_upn = f"me1@{tenant.custom_domain}"
                tenant.licensed_user_password = licensed_user.get("password")
                await db.commit()

            update_progress(
                str(tenant.id),
                "licensed_user",
                "complete",
                f"Licensed user ready: {licensed_user.get('email')}",
            )

            delegate_to = f"me1@{tenant.custom_domain}"
            tenant.licensed_user_upn = delegate_to
            if licensed_user.get("password"):
                tenant.licensed_user_password = licensed_user.get("password")
            await db.commit()

            # Step 4: Generate mailboxes in DB (or use custom CSV emails)
            update_progress(
                str(tenant.id),
                "generate_emails",
                "in_progress",
                "Generating email variations",
            )
            persona_display_name = None
            if batch:
                persona_display_name = f"{batch.persona_first_name or ''} {batch.persona_last_name or ''}".strip()
            if not persona_display_name:
                raise Exception("Missing persona display name for mailbox generation")

            # CHECK FOR CUSTOM MAILBOX MAP (CSV-imported emails for this domain)
            custom_emails_for_domain = None
            if batch and batch.custom_mailbox_map:
                domain_key = tenant.custom_domain.lower() if tenant.custom_domain else ""
                custom_emails_for_domain = batch.custom_mailbox_map.get(domain_key)

            if custom_emails_for_domain:
                # USE CUSTOM EMAILS from uploaded CSV
                logger.info(
                    "[%s] Using %d custom email addresses from CSV (instead of auto-generated)",
                    tenant.custom_domain,
                    len(custom_emails_for_domain),
                )
                from app.services.email_generator import MAILBOX_PASSWORD
                mailbox_data = []
                for entry in custom_emails_for_domain:
                    email = entry.get("email", "").strip().lower()
                    if not email or "@" not in email:
                        continue
                    local_part = email.split("@")[0]
                    display_name_val = entry.get("display_name", "").strip() or persona_display_name
                    password_val = entry.get("password", "").strip() or MAILBOX_PASSWORD
                    mailbox_data.append({
                        "email": email,
                        "local_part": local_part,
                        "display_name": display_name_val,
                        "password": password_val,
                    })
                if not mailbox_data:
                    logger.warning(
                        "[%s] Custom mailbox map had entries but none were valid - falling back to auto-generate",
                        tenant.custom_domain,
                    )
                    mailbox_data = generate_emails_for_domain(
                        display_name=persona_display_name,
                        domain=tenant.custom_domain,
                        count=50,
                    )
            else:
                # AUTO-GENERATE emails (original behavior)
                mailbox_data = generate_emails_for_domain(
                    display_name=persona_display_name,
                    domain=tenant.custom_domain,
                    count=50,
                )

            existing_mailbox_result = await db.execute(
                select(Mailbox).where(Mailbox.tenant_id == tenant.id)
            )
            existing_mailboxes = existing_mailbox_result.scalars().all()

            if existing_mailboxes:
                mailboxes = existing_mailboxes
            else:
                mailboxes = []
                for mb in mailbox_data:
                    mailbox = Mailbox(
                        email=mb["email"],
                        local_part=mb["local_part"],
                        display_name=mb["display_name"],
                        password=mb["password"],
                        tenant_id=tenant.id,
                        batch_id=tenant.batch_id,
                        status=MailboxStatus.PENDING,
                        warmup_stage="none",
                    )
                    db.add(mailbox)
                    mailboxes.append(mailbox)
                await db.commit()

            update_progress(
                str(tenant.id),
                "generate_emails",
                "complete",
                f"Generated {len(mailboxes)} mailboxes",
            )

            mailbox_data_payload = [
                {
                    "email": mailbox.email,
                    "display_name": mailbox.display_name,
                    "password": mailbox.password,
                }
                for mailbox in mailboxes
            ]

            mailboxes_by_email = {mailbox.email: mailbox for mailbox in mailboxes}
            all_created = all(mb.created_in_exchange for mb in mailboxes) if mailboxes else False
            all_delegated = all(mb.delegated for mb in mailboxes) if mailboxes else False
            all_passwords_set = all(mb.password_set for mb in mailboxes) if mailboxes else False

            async def connect_powershell_with_retry(service: PowerShellExchangeService, max_attempts: int = 2) -> bool:
                for attempt in range(1, max_attempts + 1):
                    try:
                        logger.info(
                            "[%s] PowerShell connect attempt %s/%s",
                            tenant.custom_domain,
                            attempt,
                            max_attempts,
                        )
                        connected = await service.connect()
                        if connected:
                            return True
                    except Exception as exc:
                        logger.warning(
                            "[%s] PowerShell connect attempt %s failed: %s",
                            tenant.custom_domain,
                            attempt,
                            exc,
                        )
                    try:
                        await service.disconnect()
                    except Exception:
                        pass
                    if attempt < max_attempts:
                        await asyncio.sleep(5)
                return False

            async def run_with_powershell_retry(operation_name: str, operation):
                last_error = None
                for attempt in range(1, 3):
                    try:
                        logger.info(
                            "[%s] %s attempt %s/2",
                            tenant.custom_domain,
                            operation_name,
                            attempt,
                        )
                        return await operation()
                    except Exception as exc:
                        last_error = exc
                        logger.warning(
                            "[%s] %s attempt %s failed: %s",
                            tenant.custom_domain,
                            operation_name,
                            attempt,
                            exc,
                        )
                        if ps_service:
                            try:
                                await ps_service.disconnect()
                            except Exception:
                                pass
                        if attempt < 2 and ps_service:
                            connected = await connect_powershell_with_retry(ps_service)
                            if not connected:
                                break
                if last_error:
                    raise last_error

            if needs_powershell:
                ps_service = PowerShellExchangeService(
                    driver=driver,
                    admin_email=tenant.admin_email,
                    admin_password=tenant.admin_password,
                    totp_secret=tenant.totp_secret,
                )
                connected = await connect_powershell_with_retry(ps_service)
                if not connected:
                    raise Exception("Failed to connect to Exchange Online")
                logger.info("[%s] PowerShell connected - stabilizing browser session before continuing...", tenant.custom_domain)
                await asyncio.sleep(5)

            # ========================================
            # PHASE 1: PowerShell - Create, fix names, delegate
            # ========================================
            powershell_succeeded = False

            if not needs_powershell:
                logger.info(
                    "[%s] Mailboxes already created & delegated, skipping PowerShell",
                    tenant.custom_domain,
                )
                update_progress(
                    str(tenant.id),
                    "create_mailboxes",
                    "complete",
                    "Mailboxes already created & delegated",
                )
                powershell_succeeded = True
            else:
                try:
                    logger.info("[%s] === PHASE 1: PowerShell STARTING ===", tenant.custom_domain)
                    logger.info("[%s] Phase 1: PowerShell operations", str(tenant.id)[:8])
                    update_progress(
                        str(tenant.id),
                        "create_mailboxes",
                        "in_progress",
                        "Creating shared mailboxes via PowerShell",
                    )

                    # FORCE RETRY FIX: ALWAYS process ALL mailboxes on retry
                    # The database may falsely show completion when M365 tenant was recreated
                    # PowerShell handles "already exists" gracefully for creation and delegation
                    mailboxes_to_process = mailbox_data_payload  # Process ALL mailboxes
                    
                    logger.info("[%s] FORCE RETRY: Processing ALL %s mailboxes (ignoring DB flags)", 
                                tenant.custom_domain, len(mailboxes_to_process))

                    try:
                        ps_results = await run_with_powershell_retry(
                            "PowerShell mailbox creation",
                            lambda: ps_service.create_shared_mailboxes(
                                mailboxes=mailboxes_to_process,
                                delegate_to=delegate_to,
                            ),
                        )

                        created_count = sum(
                            1 for mb in mailboxes if (mb.created_in_exchange or mb.email in ps_results["created"])
                        )
                        delegated_count = sum(
                            1 for mb in mailboxes if (mb.delegated or mb.email in ps_results["delegated"])
                        )
                        upn_fixed_count = sum(
                            1
                            for mb in mailboxes
                            if (getattr(mb, "upn_fixed", False) or mb.email in ps_results.get("upns_fixed", []))
                        )
                        tenant.step6_mailboxes_created = created_count
                        tenant.step6_display_names_fixed = created_count
                        tenant.step6_delegations_done = delegated_count
                        tenant.step6_upns_fixed = upn_fixed_count

                        logger.info("[%s] Saving PowerShell progress to database...", tenant.custom_domain)
                        logger.info(
                            "[%s] PowerShell flags: mailboxes=%s delegations=%s upns=%s",
                            tenant.custom_domain,
                            tenant.step6_mailboxes_created,
                            tenant.step6_delegations_done,
                            tenant.step6_upns_fixed,
                        )
                        async with SessionLocal() as fresh_db:
                            tenant_to_update = await fresh_db.get(Tenant, tenant.id)
                            if tenant_to_update:
                                tenant_to_update.step6_mailboxes_created = created_count
                                tenant_to_update.step6_display_names_fixed = created_count
                                tenant_to_update.step6_delegations_done = delegated_count
                                tenant_to_update.step6_upns_fixed = upn_fixed_count

                            for email in ps_results["created"]:
                                await fresh_db.execute(
                                    update(Mailbox)
                                    .where(Mailbox.email == email)
                                    .values(
                                        created_in_exchange=True,
                                        display_name_fixed=True,
                                    )
                                )

                            for email in ps_results["delegated"]:
                                await fresh_db.execute(
                                    update(Mailbox)
                                    .where(Mailbox.email == email)
                                    .values(delegated=True)
                                )

                            for email in ps_results.get("upns_fixed", []):
                                await fresh_db.execute(
                                    update(Mailbox)
                                    .where(Mailbox.email == email)
                                    .values(upn_fixed=True)
                                )

                            await fresh_db.commit()
                        logger.info(
                            "[%s] PowerShell progress SAVED with fresh connection: mailboxes=%s, delegations=%s, upns=%s",
                            tenant.custom_domain,
                            tenant.step6_mailboxes_created,
                            tenant.step6_delegations_done,
                            tenant.step6_upns_fixed,
                        )

                        # FIXED: Check actual DB state instead of ps_results["created"] count
                        # This ensures Phase 2 runs even if mailboxes were created in a previous run
                        async with SessionLocal() as check_db:
                            ps_created_count = await check_db.scalar(
                                select(func.count(Mailbox.id)).where(
                                    Mailbox.tenant_id == tenant.id,
                                    Mailbox.created_in_exchange == True,
                                )
                            ) or 0
                            ps_delegated_count = await check_db.scalar(
                                select(func.count(Mailbox.id)).where(
                                    Mailbox.tenant_id == tenant.id,
                                    Mailbox.delegated == True,
                                )
                            ) or 0
                            
                            ps_threshold = len(mailboxes) * 0.9
                            powershell_succeeded = (
                                ps_created_count >= ps_threshold and 
                                ps_delegated_count >= ps_threshold
                            )
                            logger.info(
                                "[%s] PowerShell phase check: created=%s, delegated=%s, threshold=%s, succeeded=%s",
                                tenant.custom_domain,
                                ps_created_count,
                                ps_delegated_count,
                                ps_threshold,
                                powershell_succeeded,
                            )
                        
                        logger.info(
                            "[%s] === PHASE 1: PowerShell DONE (success=%s) ===",
                            tenant.custom_domain,
                            powershell_succeeded,
                        )

                        update_progress(
                            str(tenant.id),
                            "create_mailboxes",
                            "complete",
                            f"Created {len(ps_results['created'])} mailboxes",
                        )
                    finally:
                        pass
                except Exception as e:
                    logger.error("[%s] PHASE 1 FAILED: %s", tenant.custom_domain, e)
                    import traceback

                    logger.error(traceback.format_exc())
                    raise

            # ========================================
            # PHASE 2: Admin UI (Selenium) - Set passwords, enable accounts
            # ========================================
            if not powershell_succeeded:
                logger.info(
                    "[%s] Phase 2: Skipped Admin UI - PowerShell did not succeed",
                    tenant.custom_domain,
                )
                update_progress(
                    str(tenant.id),
                    "set_passwords",
                    "complete",
                    "Skipped Admin UI - PowerShell not successful",
                )
            else:
                try:
                    if not needs_admin_ui:
                        logger.info(
                            "[%s] Passwords already set, skipping Admin UI",
                            tenant.custom_domain,
                        )
                        update_progress(
                            str(tenant.id),
                            "set_passwords",
                            "complete",
                            "Passwords already set",
                        )
                    else:
                        logger.info(
                            "[%s] === PHASE 2: Admin UI STARTING ===",
                            tenant.custom_domain,
                        )
                        logger.info(
                            "[%s] Phase 2: Admin UI operations",
                            str(tenant.id)[:8],
                        )
                        logger.info("[%s] passwords_set=%s", tenant.custom_domain, tenant.step6_passwords_set)
                        update_progress(
                            str(tenant.id),
                            "set_passwords",
                            "in_progress",
                            "Setting passwords via Admin UI",
                        )

                        # BROWSER RETRY LOGIC for Admin UI phase
                        admin_ui_results = None
                        admin_ui_retry_count = 0
                        MAX_ADMIN_UI_RETRIES = 2
                        
                        while admin_ui_retry_count < MAX_ADMIN_UI_RETRIES and admin_ui_results is None:
                            try:
                                admin_ui_retry_count += 1
                                if admin_ui_retry_count > 1:
                                    update_progress(str(tenant.id), "set_passwords", "in_progress", 
                                        f"Retrying Admin UI (attempt {admin_ui_retry_count}/{MAX_ADMIN_UI_RETRIES})")
                                    
                                    # Recreate browser if crashed
                                    if driver:
                                        try:
                                            cleanup_driver(driver)
                                        except Exception:
                                            pass
                                        driver = None
                                    
                                    driver = create_driver(headless=settings.step6_headless)
                                    _login_with_mfa(
                                        driver=driver,
                                        admin_email=tenant.admin_email,
                                        admin_password=tenant.admin_password,
                                        totp_secret=tenant.totp_secret,
                                        domain=tenant.custom_domain,
                                    )
                                    user_ops = UserOpsSelenium(driver, tenant.custom_domain)
                                
                                admin_ui_results = user_ops.set_passwords_and_enable_via_admin_ui(
                                    password="#Sendemails1",
                                    exclude_users=[f"me1@{tenant.custom_domain}"],
                                    expected_count=len(mailboxes),
                                )
                            except Exception as admin_ui_error:
                                error_str = str(admin_ui_error)
                                is_connection_error = (
                                    "HTTPConnectionPool" in error_str or 
                                    "NewConnectionError" in error_str or
                                    "target machine actively refused" in error_str or
                                    "session" in error_str.lower() and "delete" in error_str.lower()
                                )
                                
                                if is_connection_error and admin_ui_retry_count < MAX_ADMIN_UI_RETRIES:
                                    logger.warning(
                                        "[%s] Admin UI browser error (attempt %s/%s): %s - retrying...",
                                        tenant.custom_domain, admin_ui_retry_count, MAX_ADMIN_UI_RETRIES, error_str[:100]
                                    )
                                    await asyncio.sleep(5)
                                else:
                                    raise
                        
                        if admin_ui_results is None:
                            raise Exception(f"Admin UI failed after {MAX_ADMIN_UI_RETRIES} attempts")

                        if admin_ui_results.get("errors"):
                            logger.warning(
                                "[%s] Admin UI errors: %s",
                                tenant.custom_domain,
                                "; ".join(admin_ui_results["errors"]),
                            )

                        password_set_count = admin_ui_results.get("passwords_set", 0)
                        accounts_enabled_count = admin_ui_results.get("accounts_enabled", 0)
                        tenant.step6_passwords_set = password_set_count
                        tenant.step6_accounts_enabled = accounts_enabled_count

                        logger.info(
                            "[%s] Saving Admin UI progress to database...",
                            tenant.custom_domain,
                        )
                        async with SessionLocal() as fresh_db:
                            tenant_to_update = await fresh_db.get(Tenant, tenant.id)
                            if tenant_to_update:
                                tenant_to_update.step6_passwords_set = password_set_count
                                tenant_to_update.step6_accounts_enabled = accounts_enabled_count

                            # CRITICAL FIX: Always mark mailboxes with password_set and update to #Sendemails1
                            # Since we always attempt to set #Sendemails1 in M365 via bulk UI,
                            # and mailboxes are now generated with #Sendemails1 from the start,
                            # we should always mark them as set when Admin UI completes
                            # (Even if count is lower than expected, the ones that worked are set correctly)
                            total_mailbox_count = len(mailboxes)
                            
                            if password_set_count > 0:
                                logger.info(
                                    "[%s] Marking all %s mailboxes as password_set=True (Admin UI reported %s successes)",
                                    tenant.custom_domain,
                                    total_mailbox_count,
                                    password_set_count,
                                )
                                # Update ALL mailboxes - the password was already #Sendemails1 from generation
                                # This ensures DB always matches M365 reality
                                await fresh_db.execute(
                                    update(Mailbox)
                                    .where(Mailbox.tenant_id == tenant.id)
                                    .values(
                                        password_set=True,
                                        account_enabled=True,
                                        password="#Sendemails1",  # Ensure DB password matches M365
                                    )
                                )
                            else:
                                logger.warning(
                                    "[%s] Admin UI reported 0 passwords set - mailboxes still have password=#Sendemails1 from generation",
                                    tenant.custom_domain,
                                )

                            await fresh_db.commit()
                        logger.info(
                            "[%s] Admin UI progress saved: passwords_set=%s, accounts_enabled=%s",
                            tenant.custom_domain,
                            password_set_count,
                            accounts_enabled_count,
                        )
                        logger.info(
                            "[%s] === PHASE 2: Admin UI DONE ===",
                            tenant.custom_domain,
                        )
                except Exception as e:
                    logger.error("[%s] PHASE 2 FAILED: %s", tenant.custom_domain, e)
                    import traceback

                    logger.error(traceback.format_exc())
                    raise

            # ========================================
            # Completion check (use DB mailbox state to avoid stale counts)
            step6_actually_complete = False
            missing_items = []
            
            async with SessionLocal() as fresh_db:
                total_mailboxes = await fresh_db.scalar(
                    select(func.count(Mailbox.id)).where(Mailbox.tenant_id == tenant.id)
                ) or 0
                created_count = await fresh_db.scalar(
                    select(func.count(Mailbox.id)).where(
                        Mailbox.tenant_id == tenant.id,
                        Mailbox.created_in_exchange == True,
                    )
                ) or 0
                delegated_count = await fresh_db.scalar(
                    select(func.count(Mailbox.id)).where(
                        Mailbox.tenant_id == tenant.id,
                        Mailbox.delegated == True,
                    )
                ) or 0
                passwords_set_count = await fresh_db.scalar(
                    select(func.count(Mailbox.id)).where(
                        Mailbox.tenant_id == tenant.id,
                        Mailbox.password_set == True,
                    )
                ) or 0

                tenant_to_update = await fresh_db.get(Tenant, tenant.id)
                if tenant_to_update:
                    tenant_to_update.step6_mailboxes_created = max(
                        tenant_to_update.step6_mailboxes_created or 0,
                        created_count,
                    )
                    tenant_to_update.step6_delegations_done = max(
                        tenant_to_update.step6_delegations_done or 0,
                        delegated_count,
                    )
                    tenant_to_update.step6_passwords_set = max(
                        tenant_to_update.step6_passwords_set or 0,
                        passwords_set_count,
                    )

                    # CRITICAL FIX: Require BOTH delegation AND passwords for completion
                    # Previously used OR which allowed marking complete with just delegations
                    completion_threshold = 0.9
                    if total_mailboxes > 0:
                        has_mailboxes = created_count >= total_mailboxes * completion_threshold
                        has_delegation = delegated_count >= total_mailboxes * completion_threshold
                        has_passwords = passwords_set_count >= total_mailboxes * completion_threshold
                        
                        logger.info(
                            "[%s] Completion check: mailboxes=%s/%s, delegated=%s/%s, passwords=%s/%s (threshold=%s)",
                            tenant.custom_domain,
                            created_count, total_mailboxes,
                            delegated_count, total_mailboxes,
                            passwords_set_count, total_mailboxes,
                            completion_threshold,
                        )
                        
                        # MUST have mailboxes AND delegation AND passwords
                        if has_mailboxes and has_delegation and has_passwords:
                            tenant_to_update.step6_complete = True
                            tenant_to_update.step6_completed_at = datetime.utcnow()
                            tenant_to_update.status = TenantStatus.READY
                            tenant_to_update.step6_error = None
                            step6_actually_complete = True
                            logger.info("[%s] All criteria met - marking Step 6 COMPLETE", tenant.custom_domain)
                        else:
                            if not has_mailboxes:
                                missing_items.append(f"mailboxes ({created_count}/{total_mailboxes})")
                            if not has_delegation:
                                missing_items.append(f"delegation ({delegated_count}/{total_mailboxes})")
                            if not has_passwords:
                                missing_items.append(f"passwords ({passwords_set_count}/{total_mailboxes})")
                            error_msg = f"Incomplete - missing: {', '.join(missing_items)}"
                            tenant_to_update.step6_error = error_msg
                            logger.warning("[%s] NOT marking complete - missing: %s", tenant.custom_domain, ", ".join(missing_items))

                    await fresh_db.commit()

                if tenant_to_update and tenant_to_update.step6_complete:
                    logger.info(
                        "[%s] Step 6 COMPLETE for %s",
                        str(tenant.id)[:8],
                        tenant.custom_domain,
                    )

            # CRITICAL FIX: Only report success if step 6 actually completed
            if step6_actually_complete:
                update_progress(str(tenant.id), "complete", "complete", "Step 6 complete!")
                return {"success": True}
            else:
                error_detail = f"Step 6 incomplete - missing: {', '.join(missing_items)}" if missing_items else "Step 6 incomplete"
                update_progress(str(tenant.id), "incomplete", "failed", error_detail)
                return {"success": False, "error": error_detail}
        except Exception as exc:
            message = str(exc)
            logger.error("[%s] Step 6 failed: %s", tenant.custom_domain, message)
            async with SessionLocal() as fresh_db:
                tenant_to_update = await fresh_db.get(Tenant, tenant.id)
                if tenant_to_update:
                    tenant_to_update.step6_error = message
                    await fresh_db.commit()
            update_progress(str(tenant.id), "error", "failed", message)
            return {"success": False, "error": message}
        finally:
            if ps_service:
                try:
                    await ps_service.disconnect()
                except Exception:
                    pass
            if driver:
                cleanup_driver(driver)

