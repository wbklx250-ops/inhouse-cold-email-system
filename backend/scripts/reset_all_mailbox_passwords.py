"""
Bulletproof bulk mailbox password reset.

Strategy:
1) Selenium login (handles MFA) to obtain Graph API token via OAuth consent.
2) Use Graph API PATCH /users/{upn} to reset passwords and enable accounts.
3) Immediate DB commits per mailbox with retries.
4) Verification pass to confirm accountEnabled = true for every mailbox.

Usage:
    python -m scripts.reset_all_mailbox_passwords
    python -m scripts.reset_all_mailbox_passwords --headless
    python -m scripts.reset_all_mailbox_passwords --tenant-id <uuid>
    python -m scripts.reset_all_mailbox_passwords --dry-run
    python -m scripts.reset_all_mailbox_passwords --force
    python -m scripts.reset_all_mailbox_passwords --skip-verify
    python -m scripts.reset_all_mailbox_passwords --selenium-fallback
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import aiohttp
from sqlalchemy import select, update
from sqlalchemy.exc import InterfaceError, OperationalError
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from app.db.session import async_session_factory
from app.models.mailbox import Mailbox
from app.models.tenant import Tenant
from app.services.graph_auth import get_graph_token_resilient
from app.services.selenium.admin_portal import _login_with_mfa
from app.services.selenium.user_ops import UserOpsSelenium

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reset_mailbox_passwords")

MAILBOX_PASSWORD = "#Sendemails1"
TOKEN_EXPIRY_BUFFER = timedelta(minutes=5)
TOKEN_DEFAULT_TTL = timedelta(minutes=55)
REPORT_DIR = "C:/temp/password_reset_reports"


def configure_logging() -> None:
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    os.environ.setdefault("GRPC_VERBOSITY", "ERROR")


@dataclass
class MailboxResetResult:
    mailbox_id: str
    upn: str
    success: bool
    skipped: bool = False
    error: Optional[str] = None
    verified: bool = False


@dataclass
class TenantResetSummary:
    tenant_id: str
    domain: str
    total_mailboxes: int
    attempted: int
    succeeded: int
    skipped: int
    failed: int
    verified: int
    errors: List[str]


def build_driver(headless: bool) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    profile_dir = tempfile.mkdtemp(prefix=f"reset-pwd-{uuid.uuid4()}-")
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    driver = webdriver.Chrome(options=options)
    driver._profile_dir = profile_dir
    return driver


def cleanup_driver(driver: Optional[webdriver.Chrome]) -> None:
    if not driver:
        return
    profile_dir = getattr(driver, "_profile_dir", None)
    try:
        driver.quit()
    except Exception:
        pass
    if profile_dir:
        try:
            shutil.rmtree(profile_dir, ignore_errors=True)
        except Exception:
            pass


def get_auth_domain(tenant: Tenant) -> str:
    return tenant.onmicrosoft_domain or tenant.custom_domain or tenant.microsoft_tenant_id


def token_still_valid(tenant: Tenant) -> bool:
    if not tenant.access_token or not tenant.token_expires_at:
        return False
    expires_at = tenant.token_expires_at
    if isinstance(expires_at, datetime):
        return expires_at > datetime.now(timezone.utc) + TOKEN_EXPIRY_BUFFER
    return False


async def fetch_tenants(tenant_id: Optional[str] = None) -> List[Tenant]:
    async with async_session_factory() as session:
        query = select(Tenant)
        if tenant_id:
            query = query.where(Tenant.id == tenant_id)
        result = await session.execute(query)
        return list(result.scalars().all())


async def fetch_mailboxes_for_tenant(tenant_id: str) -> List[Mailbox]:
    async with async_session_factory() as session:
        result = await session.execute(
            select(Mailbox).where(Mailbox.tenant_id == tenant_id)
        )
        return list(result.scalars().all())


async def update_tenant_token(tenant_id: str, token: str) -> None:
    async with async_session_factory() as session:
        await session.execute(
            update(Tenant)
            .where(Tenant.id == tenant_id)
            .values(
                access_token=token,
                token_expires_at=datetime.now(timezone.utc) + TOKEN_DEFAULT_TTL,
            )
        )
        await session.commit()


async def update_mailbox_state(
    mailbox_id: str,
    values: Dict[str, Any],
    max_retries: int = 4,
) -> bool:
    last_error: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            async with async_session_factory() as session:
                await session.execute(
                    update(Mailbox)
                    .where(Mailbox.id == mailbox_id)
                    .values(**values)
                )
                await session.commit()
            return True
        except (InterfaceError, OperationalError) as exc:
            last_error = exc
            logger.warning(
                "DB update failed (attempt %s/%s) for mailbox %s: %s",
                attempt + 1,
                max_retries,
                mailbox_id,
                exc,
            )
            await asyncio.sleep(2 ** attempt)
        except Exception as exc:
            last_error = exc
            logger.error(
                "DB update failed (attempt %s/%s) for mailbox %s: %s",
                attempt + 1,
                max_retries,
                mailbox_id,
                exc,
            )
            await asyncio.sleep(2 ** attempt)
    if last_error:
        logger.error("DB update permanently failed for mailbox %s: %s", mailbox_id, last_error)
    return False


def acquire_graph_token_sync(tenant: Tenant, headless: bool) -> Optional[str]:
    driver = build_driver(headless=headless)
    try:
        _login_with_mfa(
            driver=driver,
            admin_email=tenant.admin_email,
            admin_password=tenant.admin_password,
            totp_secret=tenant.totp_secret,
            domain=tenant.custom_domain or tenant.onmicrosoft_domain,
        )
        auth_domain = get_auth_domain(tenant)
        token = get_graph_token_resilient(driver, auth_domain)
        return token
    except Exception as exc:
        logger.error("Token acquisition failed for %s: %s", tenant.custom_domain, exc)
        return None
    finally:
        cleanup_driver(driver)


async def acquire_graph_token(tenant: Tenant, headless: bool) -> Optional[str]:
    return await asyncio.to_thread(acquire_graph_token_sync, tenant, headless)


class GraphClient:
    def __init__(
        self,
        token: str,
        session: aiohttp.ClientSession,
        refresh_cb: Optional[Callable[[], asyncio.Future]] = None,
    ) -> None:
        self._token = token
        self._session = session
        self._refresh_cb = refresh_cb

    @property
    def token(self) -> str:
        return self._token

    async def refresh_token(self) -> bool:
        if not self._refresh_cb:
            return False
        new_token = await self._refresh_cb()
        if new_token:
            self._token = new_token
            return True
        return False

    async def request(
        self,
        method: str,
        endpoint: str,
        payload: Optional[Dict[str, Any]] = None,
        expected_status: Iterable[int] = (200, 204),
        max_retries: int = 5,
    ) -> Tuple[bool, int, str, Optional[Dict[str, Any]]]:
        url = f"https://graph.microsoft.com/v1.0{endpoint}"
        for attempt in range(1, max_retries + 1):
            headers = {
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            }
            try:
                async with self._session.request(
                    method,
                    url,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as response:
                    status = response.status
                    text = await response.text()
                    if status in expected_status:
                        data = None
                        if text:
                            try:
                                data = await response.json()
                            except Exception:
                                data = None
                        return True, status, text, data
                    if status == 401 and await self.refresh_token():
                        logger.warning("Graph token refreshed after 401, retrying...")
                        continue
                    if status == 429:
                        retry_after = int(response.headers.get("Retry-After", "5"))
                        logger.warning("Graph throttled (429). Waiting %ss...", retry_after)
                        await asyncio.sleep(retry_after)
                        continue
                    if 500 <= status < 600:
                        wait = min(30, 2 ** attempt)
                        logger.warning(
                            "Graph server error %s (attempt %s/%s). Waiting %ss...",
                            status,
                            attempt,
                            max_retries,
                            wait,
                        )
                        await asyncio.sleep(wait)
                        continue
                    return False, status, text, None
            except asyncio.TimeoutError:
                wait = min(30, 2 ** attempt)
                logger.warning("Graph request timed out (attempt %s/%s). Waiting %ss...", attempt, max_retries, wait)
                await asyncio.sleep(wait)
            except Exception as exc:
                wait = min(30, 2 ** attempt)
                logger.warning("Graph request failed (attempt %s/%s): %s", attempt, max_retries, exc)
                await asyncio.sleep(wait)
        return False, 0, "Max retries exceeded", None

    async def set_password_and_enable(self, upn: str, password: str) -> Tuple[bool, str]:
        payload = {
            "accountEnabled": True,
            "passwordProfile": {
                "forceChangePasswordNextSignIn": False,
                "password": password,
            },
        }
        ok, status, text, _ = await self.request(
            "PATCH",
            f"/users/{upn}",
            payload=payload,
            expected_status=(204,),
        )
        if ok:
            return True, ""
        return False, f"PATCH failed ({status}): {text}"

    async def verify_enabled(self, upn: str) -> Tuple[bool, str]:
        ok, status, text, data = await self.request(
            "GET",
            f"/users/{upn}?$select=id,accountEnabled",
            expected_status=(200,),
        )
        if not ok:
            return False, f"GET failed ({status}): {text}"
        if not data:
            return False, "GET returned empty response"
        if data.get("accountEnabled") is True:
            return True, ""
        return False, "accountEnabled is false"


async def reset_mailbox(
    graph: GraphClient,
    mailbox: Mailbox,
    password: str,
    semaphore: asyncio.Semaphore,
    force: bool,
    dry_run: bool,
    max_attempts: int = 3,
) -> MailboxResetResult:
    upn = (mailbox.upn or mailbox.email or "").lower()
    if not upn:
        return MailboxResetResult(
            mailbox_id=str(mailbox.id),
            upn="",
            success=False,
            error="Mailbox missing UPN/email",
        )

    if not force and mailbox.password_set and mailbox.password == password:
        return MailboxResetResult(
            mailbox_id=str(mailbox.id),
            upn=upn,
            success=True,
            skipped=True,
            verified=True,
        )

    if dry_run:
        return MailboxResetResult(
            mailbox_id=str(mailbox.id),
            upn=upn,
            success=True,
            skipped=True,
            verified=True,
        )

    async with semaphore:
        for attempt in range(1, max_attempts + 1):
            ok, error = await graph.set_password_and_enable(upn, password)
            if ok:
                verified, verify_error = await graph.verify_enabled(upn)
                if verified:
                    await update_mailbox_state(
                        str(mailbox.id),
                        {
                            "password": password,
                            "initial_password": password,
                            "password_set": True,
                            "account_enabled": True,
                            "error_message": None,
                        },
                    )
                    return MailboxResetResult(
                        mailbox_id=str(mailbox.id),
                        upn=upn,
                        success=True,
                        verified=True,
                    )
                error = f"Verification failed: {verify_error}"
            wait = min(15, 2 ** attempt)
            logger.warning("Reset attempt %s/%s failed for %s: %s", attempt, max_attempts, upn, error)
            await asyncio.sleep(wait)

        await update_mailbox_state(
            str(mailbox.id),
            {
                "error_message": f"Password reset failed after {max_attempts} attempts",
            },
        )
        return MailboxResetResult(
            mailbox_id=str(mailbox.id),
            upn=upn,
            success=False,
            error=f"Failed after {max_attempts} attempts",
        )


async def verify_mailbox_state(
    graph: GraphClient,
    mailbox: Mailbox,
    semaphore: asyncio.Semaphore,
    password: str,
) -> MailboxResetResult:
    upn = (mailbox.upn or mailbox.email or "").lower()
    if not upn:
        return MailboxResetResult(
            mailbox_id=str(mailbox.id),
            upn="",
            success=False,
            error="Mailbox missing UPN/email",
        )
    async with semaphore:
        verified, error = await graph.verify_enabled(upn)
        if verified:
            await update_mailbox_state(
                str(mailbox.id),
                {
                    "password": password,
                    "initial_password": password,
                    "password_set": True,
                    "account_enabled": True,
                    "error_message": None,
                },
            )
            return MailboxResetResult(
                mailbox_id=str(mailbox.id),
                upn=upn,
                success=True,
                verified=True,
            )
        return MailboxResetResult(
            mailbox_id=str(mailbox.id),
            upn=upn,
            success=False,
            verified=False,
            error=error,
        )


async def run_selenium_fallback(tenant: Tenant, headless: bool, password: str) -> bool:
    logger.warning("Using Selenium fallback for tenant %s", tenant.custom_domain)
    driver = build_driver(headless=headless)
    user_ops = UserOpsSelenium(driver, tenant.custom_domain)
    try:
        _login_with_mfa(
            driver=driver,
            admin_email=tenant.admin_email,
            admin_password=tenant.admin_password,
            totp_secret=tenant.totp_secret,
            domain=tenant.custom_domain,
        )
        bulk_results = user_ops.set_passwords_and_enable_via_admin_ui(
            password=password,
            exclude_users=["me1"],
            expected_count=tenant.target_mailbox_count,
        )
        errors = bulk_results.get("errors", [])
        return not errors
    finally:
        cleanup_driver(driver)


async def run_for_tenant(
    tenant: Tenant,
    headless: bool,
    force: bool,
    dry_run: bool,
    concurrency: int,
    verify_all: bool,
    selenium_fallback: bool,
) -> TenantResetSummary:
    logger.info("Processing tenant %s (%s)", tenant.name, tenant.custom_domain)

    mailboxes = await fetch_mailboxes_for_tenant(str(tenant.id))
    total_mailboxes = len(mailboxes)
    if not mailboxes:
        return TenantResetSummary(
            tenant_id=str(tenant.id),
            domain=tenant.custom_domain or tenant.onmicrosoft_domain or "",
            total_mailboxes=0,
            attempted=0,
            succeeded=0,
            skipped=0,
            failed=0,
            verified=0,
            errors=["No mailboxes found"],
        )

    token: Optional[str] = None
    if token_still_valid(tenant):
        token = tenant.access_token
        logger.info("Using cached Graph token for tenant %s", tenant.custom_domain)

    if not token:
        token = await acquire_graph_token(tenant, headless=headless)
        if token:
            await update_tenant_token(str(tenant.id), token)

    if not token:
        if selenium_fallback:
            success = await run_selenium_fallback(tenant, headless=headless, password=MAILBOX_PASSWORD)
            status = "Selenium fallback failed" if not success else "Selenium fallback success"
            return TenantResetSummary(
                tenant_id=str(tenant.id),
                domain=tenant.custom_domain or tenant.onmicrosoft_domain or "",
                total_mailboxes=total_mailboxes,
                attempted=0,
                succeeded=0,
                skipped=0,
                failed=total_mailboxes if not success else 0,
                verified=0,
                errors=[status],
            )
        return TenantResetSummary(
            tenant_id=str(tenant.id),
            domain=tenant.custom_domain or tenant.onmicrosoft_domain or "",
            total_mailboxes=total_mailboxes,
            attempted=0,
            succeeded=0,
            skipped=0,
            failed=total_mailboxes,
            verified=0,
            errors=["Failed to acquire Graph token"],
        )

    async def refresh_token() -> Optional[str]:
        new_token = await acquire_graph_token(tenant, headless=headless)
        if new_token:
            await update_tenant_token(str(tenant.id), new_token)
        return new_token

    semaphore = asyncio.Semaphore(concurrency)
    results: List[MailboxResetResult] = []
    async with aiohttp.ClientSession() as session:
        graph = GraphClient(token=token, session=session, refresh_cb=refresh_token)
        tasks = [
            reset_mailbox(
                graph,
                mailbox,
                MAILBOX_PASSWORD,
                semaphore,
                force=force,
                dry_run=dry_run,
            )
            for mailbox in mailboxes
        ]
        results = await asyncio.gather(*tasks)

        if verify_all and not dry_run:
            verify_tasks = [
                verify_mailbox_state(graph, mailbox, semaphore, MAILBOX_PASSWORD)
                for mailbox in mailboxes
            ]
            verify_results = await asyncio.gather(*verify_tasks)
            for verify_result in verify_results:
                if not verify_result.success:
                    logger.warning("Verification failed for %s: %s", verify_result.upn, verify_result.error)

    succeeded = sum(1 for r in results if r.success and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    failed = sum(1 for r in results if not r.success)
    verified = sum(1 for r in results if r.verified)
    errors = [r.error for r in results if r.error]

    return TenantResetSummary(
        tenant_id=str(tenant.id),
        domain=tenant.custom_domain or tenant.onmicrosoft_domain or "",
        total_mailboxes=total_mailboxes,
        attempted=len(results),
        succeeded=succeeded,
        skipped=skipped,
        failed=failed,
        verified=verified,
        errors=errors,
    )


def write_report(tenant_summaries: List[TenantResetSummary]) -> str:
    os.makedirs(REPORT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(REPORT_DIR, f"bulk_password_reset_{timestamp}.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(
            [summary.__dict__ for summary in tenant_summaries],
            handle,
            indent=2,
            default=str,
        )
    return path


async def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument("--tenant-id", help="Optional tenant UUID to process a single tenant")
    parser.add_argument("--dry-run", action="store_true", help="Do not modify any accounts")
    parser.add_argument("--force", action="store_true", help="Reset even if mailbox is already updated")
    parser.add_argument("--skip-verify", action="store_true", help="Skip verification pass")
    parser.add_argument("--max-concurrency", type=int, default=10, help="Max concurrent Graph requests")
    parser.add_argument("--selenium-fallback", action="store_true", help="Fallback to UI automation if Graph fails")
    args = parser.parse_args()

    tenants = await fetch_tenants(args.tenant_id)
    if not tenants:
        logger.info("No tenants found")
        return

    summaries: List[TenantResetSummary] = []
    for tenant in tenants:
        summary = await run_for_tenant(
            tenant,
            headless=args.headless,
            force=args.force,
            dry_run=args.dry_run,
            concurrency=max(1, args.max_concurrency),
            verify_all=not args.skip_verify,
            selenium_fallback=args.selenium_fallback,
        )
        summaries.append(summary)
        logger.info(
            "Tenant %s summary: attempted=%s success=%s skipped=%s failed=%s verified=%s",
            summary.domain,
            summary.attempted,
            summary.succeeded,
            summary.skipped,
            summary.failed,
            summary.verified,
        )

    report_path = write_report(summaries)
    total_attempted = sum(s.attempted for s in summaries)
    total_succeeded = sum(s.succeeded for s in summaries)
    total_skipped = sum(s.skipped for s in summaries)
    total_failed = sum(s.failed for s in summaries)
    total_verified = sum(s.verified for s in summaries)

    logger.info(
        "Bulk reset complete: attempted=%s success=%s skipped=%s failed=%s verified=%s",
        total_attempted,
        total_succeeded,
        total_skipped,
        total_failed,
        total_verified,
    )
    logger.info("Report written to %s", report_path)


if __name__ == "__main__":
    asyncio.run(main())