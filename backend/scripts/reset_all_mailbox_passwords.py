"""
Reset all mailbox passwords to #Sendemails1 and update the database.

Usage:
    python -m scripts.reset_all_mailbox_passwords
    python -m scripts.reset_all_mailbox_passwords --headless
    python -m scripts.reset_all_mailbox_passwords --tenant-id <uuid>
"""

import argparse
import asyncio
import logging

from sqlalchemy import select, update

from app.db.session import async_session_factory
from app.models.mailbox import Mailbox
from app.models.tenant import Tenant
from app.services.selenium.user_ops import UserOpsSelenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reset_mailbox_passwords")

MAILBOX_PASSWORD = "#Sendemails1"


def build_driver(headless: bool) -> webdriver.Chrome:
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    if headless:
        options.add_argument("--headless=new")
    return webdriver.Chrome(options=options)


async def fetch_tenants(tenant_id: str | None = None):
    async with async_session_factory() as session:
        query = select(Tenant)
        if tenant_id:
            query = query.where(Tenant.id == tenant_id)
        result = await session.execute(query)
        return result.scalars().all()


async def fetch_mailboxes_for_tenant(tenant_id: str):
    async with async_session_factory() as session:
        result = await session.execute(
            select(Mailbox).where(Mailbox.tenant_id == tenant_id)
        )
        return result.scalars().all()


async def update_mailboxes_passwords(mailbox_ids: list[str]):
    if not mailbox_ids:
        return
    async with async_session_factory() as session:
        await session.execute(
            update(Mailbox)
            .where(Mailbox.id.in_(mailbox_ids))
            .values(
                password=MAILBOX_PASSWORD,
                initial_password=MAILBOX_PASSWORD,
            )
        )
        await session.commit()


async def run_for_tenant(tenant: Tenant, headless: bool):
    logger.info("Processing tenant %s (%s)", tenant.name, tenant.custom_domain)

    driver = build_driver(headless=headless)
    user_ops = UserOpsSelenium(driver, tenant.custom_domain)

    try:
        mailboxes = await fetch_mailboxes_for_tenant(str(tenant.id))
        if not mailboxes:
            logger.info("No mailboxes found for tenant %s", tenant.custom_domain)
            return

        # Login via existing admin portal login flow
        from app.services.selenium.admin_portal import _login_with_mfa

        _login_with_mfa(
            driver=driver,
            admin_email=tenant.admin_email,
            admin_password=tenant.admin_password,
            totp_secret=tenant.totp_secret,
            domain=tenant.custom_domain,
        )

        logger.info("Logged in for tenant %s", tenant.custom_domain)

        expected_count = len(mailboxes)
        bulk_results = user_ops.set_passwords_and_enable_via_admin_ui(
            password=MAILBOX_PASSWORD,
            exclude_users=["me1"],
            expected_count=expected_count,
        )

        reset_count = int(bulk_results.get("passwords_set", 0))
        error_list = bulk_results.get("errors", [])

        if reset_count >= expected_count and not error_list:
            await update_mailboxes_passwords([str(mb.id) for mb in mailboxes])
            logger.info(
                "Tenant %s: updated %s/%s mailboxes",
                tenant.custom_domain,
                reset_count,
                expected_count,
            )
        else:
            logger.warning(
                "Tenant %s: password reset incomplete (reset=%s expected=%s errors=%s)",
                tenant.custom_domain,
                reset_count,
                expected_count,
                error_list,
            )
    finally:
        try:
            driver.quit()
        except Exception:
            pass


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument("--tenant-id", help="Optional tenant UUID to process a single tenant")
    args = parser.parse_args()

    tenants = await fetch_tenants(args.tenant_id)
    if not tenants:
        logger.info("No tenants found")
        return

    for tenant in tenants:
        await run_for_tenant(tenant, headless=args.headless)


if __name__ == "__main__":
    asyncio.run(main())