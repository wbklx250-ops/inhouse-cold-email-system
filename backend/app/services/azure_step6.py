"""
Step 6 Orchestrator (Selenium + PowerShell)

Uses Selenium to create licensed user and PowerShell device code auth
to create shared mailboxes, set passwords, and add delegation.
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

from app.db.session import SessionLocal, async_session_factory
from app.models.batch import SetupBatch
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
        for tenant in tenants:
            tenant_result = await run_step6_for_tenant(tenant.id)
            results.append({"tenant_id": str(tenant.id), "result": tenant_result})

        return {
            "success": True,
            "total": len(tenants),
            "results": results,
        }


async def run_step6_for_tenant(tenant_id: UUID) -> Dict[str, Any]:
    """Run Step 6 for a single tenant using Selenium + PowerShell + Graph API."""
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

        needs_powershell = not (tenant.step6_mailboxes_created and tenant.step6_delegations_done)
        needs_admin_ui = not tenant.step6_passwords_set

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
        try:
            batch = None
            if tenant.batch_id:
                batch = await db.get(SetupBatch, tenant.batch_id)

            # Step 1: Selenium login to Admin Portal
            update_progress(str(tenant.id), "login", "in_progress", "Logging into M365 Admin Portal...")
            driver = create_driver(headless=False)
            _login_with_mfa(
                driver=driver,
                admin_email=tenant.admin_email,
                admin_password=tenant.admin_password,
                totp_secret=tenant.totp_secret,
                domain=tenant.custom_domain,
            )
            update_progress(str(tenant.id), "login", "complete", "Logged in successfully")

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

            # Step 4: Generate 50 mailboxes in DB
            update_progress(
                str(tenant.id),
                "generate_emails",
                "in_progress",
                "Generating 50 email variations",
            )
            persona_display_name = None
            if batch:
                persona_display_name = f"{batch.persona_first_name or ''} {batch.persona_last_name or ''}".strip()
            if not persona_display_name:
                raise Exception("Missing persona display name for mailbox generation")

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

                    mailboxes_to_create = [
                        mb for mb in mailbox_data_payload
                        if not mailboxes_by_email.get(mb["email"]).created_in_exchange
                    ]

                    try:
                        ps_results = await run_with_powershell_retry(
                            "PowerShell mailbox creation",
                            lambda: ps_service.create_shared_mailboxes(
                                mailboxes=mailboxes_to_create,
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

                        powershell_succeeded = (
                            len(ps_results.get("created", [])) > 0
                            or (tenant.step6_mailboxes_created and tenant.step6_delegations_done)
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

                        admin_ui_results = user_ops.set_passwords_and_enable_via_admin_ui(
                            password="#Sendemails1",
                            exclude_users=[f"me1@{tenant.custom_domain}"],
                            expected_count=len(mailboxes),
                        )

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

                            await fresh_db.execute(
                                update(Mailbox)
                                .where(Mailbox.tenant_id == tenant.id)
                                .values(
                                    password_set=True,
                                    account_enabled=True,
                                )
                            )

                            await fresh_db.commit()
                        logger.info(
                            "[%s] Admin UI progress saved: passwords_set=%s",
                            tenant.custom_domain,
                            password_set_count,
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
                        tenant_to_update.step6_mailboxes_created,
                        created_count,
                    )
                    tenant_to_update.step6_delegations_done = max(
                        tenant_to_update.step6_delegations_done,
                        delegated_count,
                    )
                    tenant_to_update.step6_passwords_set = max(
                        tenant_to_update.step6_passwords_set,
                        passwords_set_count,
                    )

                    completion_threshold = 0.9
                    if total_mailboxes > 0:
                        has_mailboxes = created_count >= total_mailboxes * completion_threshold
                        has_access = (
                            delegated_count >= total_mailboxes * completion_threshold
                            or passwords_set_count >= total_mailboxes * completion_threshold
                        )
                        if has_mailboxes and has_access:
                            tenant_to_update.step6_complete = True
                            tenant_to_update.step6_completed_at = datetime.utcnow()
                            tenant_to_update.status = TenantStatus.READY
                            tenant_to_update.step6_error = None

                    await fresh_db.commit()

                if tenant_to_update and tenant_to_update.step6_complete:
                    logger.info(
                        "[%s] Step 6 COMPLETE for %s",
                        str(tenant.id)[:8],
                        tenant.custom_domain,
                    )

            update_progress(str(tenant.id), "complete", "complete", "Step 6 complete!")
            return {"success": True}
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

