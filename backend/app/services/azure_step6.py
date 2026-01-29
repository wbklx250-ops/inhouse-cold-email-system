"""
Step 6 Orchestrator (Selenium + PowerShell)

Uses Selenium to create licensed user and PowerShell device code auth
to create shared mailboxes, set passwords, and add delegation.
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, Any, List
from uuid import UUID

from sqlalchemy import select, update

from app.db.session import async_session_factory
from app.models.batch import SetupBatch
from app.models.mailbox import Mailbox, MailboxStatus
from app.models.tenant import Tenant, TenantStatus
from app.services.email_generator import generate_emails_for_domain
from app.services.graph_device_code import GraphDeviceCodeAuth, set_passwords_via_graph
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
        needs_graph_api = not tenant.step6_passwords_set

        if needs_powershell:
            logger.info("[%s] RUNNING PowerShell...", tenant.custom_domain)
        else:
            logger.info("[%s] SKIPPING PowerShell - already done", tenant.custom_domain)

        if needs_graph_api:
            logger.info("[%s] RUNNING Graph API...", tenant.custom_domain)
        else:
            logger.info("[%s] SKIPPING Graph API - already done", tenant.custom_domain)

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

            # ========================================
            # PHASE 1: PowerShell - Create, fix names, delegate
            # ========================================
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
            else:
                logger.info("[%s] Phase 1: PowerShell operations", str(tenant.id)[:8])
                update_progress(
                    str(tenant.id),
                    "create_mailboxes",
                    "in_progress",
                    "Creating shared mailboxes via PowerShell",
                )

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                ps_service = PowerShellExchangeService(
                    driver=driver,
                    admin_email=tenant.admin_email,
                    admin_password=tenant.admin_password,
                    totp_secret=tenant.totp_secret,
                )

                mailboxes_to_create = [
                    mb for mb in mailbox_data_payload
                    if not mailboxes_by_email.get(mb["email"]).created_in_exchange
                ]

                try:
                    connected = loop.run_until_complete(ps_service.connect())
                    if not connected:
                        raise Exception("Failed to connect to Exchange Online")

                    ps_results = loop.run_until_complete(
                        ps_service.create_shared_mailboxes(
                            mailboxes=mailboxes_to_create,
                            delegate_to=delegate_to,
                        )
                    )

                    for email in ps_results["created"]:
                        await db.execute(
                            update(Mailbox)
                            .where(Mailbox.email == email)
                            .values(
                                created_in_exchange=True,
                                display_name_fixed=True,
                            )
                        )

                    for email in ps_results["delegated"]:
                        await db.execute(
                            update(Mailbox)
                            .where(Mailbox.email == email)
                            .values(delegated=True)
                        )

                    for email in ps_results.get("upns_fixed", []):
                        await db.execute(
                            update(Mailbox)
                            .where(Mailbox.email == email)
                            .values(upn_fixed=True)
                        )

                    created_count = sum(
                        1 for mb in mailboxes if (mb.created_in_exchange or mb.email in ps_results["created"])
                    )
                    delegated_count = sum(
                        1 for mb in mailboxes if (mb.delegated or mb.email in ps_results["delegated"])
                    )
                    upn_fixed_count = sum(
                        1 for mb in mailboxes if (getattr(mb, "upn_fixed", False) or mb.email in ps_results.get("upns_fixed", []))
                    )
                    tenant.step6_mailboxes_created = created_count
                    tenant.step6_display_names_fixed = created_count
                    tenant.step6_delegations_done = delegated_count
                    tenant.step6_upns_fixed = upn_fixed_count
                    await db.commit()
                    logger.info("[%s] PowerShell progress saved to database", tenant.custom_domain)

                    update_progress(
                        str(tenant.id),
                        "create_mailboxes",
                        "complete",
                        f"Created {len(ps_results['created'])} mailboxes",
                    )
                finally:
                    await ps_service.disconnect()
                    loop.close()

            # ========================================
            # PHASE 2: Graph API - Set passwords, enable accounts
            # ========================================
            if not needs_graph_api:
                logger.info("[%s] Passwords already set, skipping Graph API", tenant.custom_domain)
                update_progress(
                    str(tenant.id),
                    "set_passwords",
                    "complete",
                    "Passwords already set",
                )
            else:
                logger.info("[%s] Phase 2: Graph API operations", str(tenant.id)[:8])
                update_progress(
                    str(tenant.id),
                    "set_passwords",
                    "in_progress",
                    "Setting passwords via Graph API",
                )

                graph_auth = GraphDeviceCodeAuth(
                    driver=driver,
                    tenant_domain=tenant.onmicrosoft_domain,
                    admin_email=tenant.admin_email,
                    admin_password=tenant.admin_password,
                    totp_secret=tenant.totp_secret,
                )

                access_token = await graph_auth.get_token()

                mailboxes_to_update = [
                    mb for mb in mailbox_data_payload
                    if not mailboxes_by_email.get(mb["email"]).password_set
                ]

                graph_results = await set_passwords_via_graph(
                    access_token=access_token,
                    mailboxes=mailboxes_to_update,
                )

                for email in graph_results["success"]:
                    await db.execute(
                        update(Mailbox)
                        .where(Mailbox.email == email)
                        .values(
                            password_set=True,
                            account_enabled=True,
                        )
                    )

                password_set_count = sum(
                    1 for mb in mailboxes if (mb.password_set or mb.email in graph_results["success"])
                )
                tenant.step6_passwords_set = password_set_count
                tenant.step6_accounts_enabled = password_set_count

            # ========================================
            # Mark complete
            # ========================================
            if (
                tenant.step6_mailboxes_created >= len(mailboxes) * 0.9
                and tenant.step6_delegations_done >= len(mailboxes) * 0.9
                and tenant.step6_passwords_set >= len(mailboxes) * 0.9
            ):
                tenant.step6_complete = True
                tenant.status = "ready"
                tenant.step6_error = None
                logger.info("[%s]  Step 6 COMPLETE for %s", str(tenant.id)[:8], tenant.custom_domain)

            await db.commit()
            update_progress(str(tenant.id), "complete", "complete", "Step 6 complete!")
            return {"success": True}
        except Exception as exc:
            message = str(exc)
            logger.error("[%s] Step 6 failed: %s", tenant.custom_domain, message)
            tenant.step6_error = message
            await db.commit()
            update_progress(str(tenant.id), "error", "failed", message)
            return {"success": False, "error": message}
        finally:
            if driver:
                cleanup_driver(driver)

