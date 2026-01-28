"""
Webhook endpoints for Azure Automation callbacks.
"""

import logging
from typing import Dict, Any, List

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import update

from app.db.session import SessionLocal
from app.models.tenant import Tenant
from app.models.mailbox import Mailbox

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/webhooks/azure", tags=["webhooks"])


class MailboxCreationResult(BaseModel):
    """Result from Azure Automation mailbox creation."""

    created: List[str] = []
    failed: List[Dict[str, str]] = []
    error: str | None = None


class DisplayNameResult(BaseModel):
    """Result from Azure Automation display name fix."""

    updated: List[str] = []
    failed: List[Dict[str, str]] = []
    error: str | None = None


class DelegationResult(BaseModel):
    """Result from Azure Automation delegation setup."""

    delegated: List[str] = []
    failed: List[Dict[str, str]] = []
    error: str | None = None


@router.post("/mailboxes/{tenant_id}")
async def mailbox_creation_callback(
    tenant_id: str,
    result: MailboxCreationResult,
    background_tasks: BackgroundTasks,
):
    """
    Callback from Azure Automation after mailbox creation.
    Updates tenant and mailbox records with results.
    """

    logger.info(
        "[%s] Received mailbox creation callback: %s created, %s failed",
        tenant_id[:8],
        len(result.created),
        len(result.failed),
    )

    if result.error:
        logger.error("[%s] Azure Automation error: %s", tenant_id[:8], result.error)

    background_tasks.add_task(
        _process_mailbox_creation_results,
        tenant_id,
        result.created,
        result.failed,
        result.error,
    )

    return {"status": "received"}


@router.post("/displaynames/{tenant_id}")
async def display_name_callback(
    tenant_id: str,
    result: DisplayNameResult,
    background_tasks: BackgroundTasks,
):
    """Callback from Azure Automation after display name fix."""

    logger.info(
        "[%s] Received display name callback: %s updated",
        tenant_id[:8],
        len(result.updated),
    )

    background_tasks.add_task(
        _process_display_name_results,
        tenant_id,
        result.updated,
        result.failed,
        result.error,
    )

    return {"status": "received"}


@router.post("/delegation/{tenant_id}")
async def delegation_callback(
    tenant_id: str,
    result: DelegationResult,
    background_tasks: BackgroundTasks,
):
    """Callback from Azure Automation after delegation setup."""

    logger.info(
        "[%s] Received delegation callback: %s delegated",
        tenant_id[:8],
        len(result.delegated),
    )

    background_tasks.add_task(
        _process_delegation_results,
        tenant_id,
        result.delegated,
        result.failed,
        result.error,
    )

    return {"status": "received"}


async def _process_mailbox_creation_results(
    tenant_id: str,
    created: List[str],
    failed: List[Dict[str, str]],
    error: str | None,
):
    """Process mailbox creation results and update database."""

    async with SessionLocal() as db:
        try:
            for email in created:
                await db.execute(
                    update(Mailbox)
                    .where(Mailbox.email == email)
                    .values(
                        created_in_m365=True,
                        m365_id=email,
                    )
                )

            for failure in failed:
                logger.error("[%s] Mailbox creation failed: %s", tenant_id[:8], failure)
                await db.execute(
                    update(Mailbox)
                    .where(Mailbox.email == failure.get("email"))
                    .values(error=failure.get("error", "Unknown error"))
                )

            await db.execute(
                update(Tenant)
                .where(Tenant.id == tenant_id)
                .values(
                    step6_mailboxes_created=True,
                    mailboxes_created=True,
                )
            )

            await db.commit()
            logger.info("[%s] Mailbox creation results processed", tenant_id[:8])

        except Exception as exc:
            logger.error(
                "[%s] Failed to process mailbox results: %s", tenant_id[:8], exc
            )
            await db.rollback()


async def _process_display_name_results(
    tenant_id: str,
    updated: List[str],
    failed: List[Dict[str, str]],
    error: str | None,
):
    """Process display name fix results."""

    async with SessionLocal() as db:
        try:
            await db.execute(
                update(Tenant)
                .where(Tenant.id == tenant_id)
                .values(step6_display_names_fixed=True)
            )

            await db.commit()
            logger.info("[%s] Display name results processed", tenant_id[:8])

        except Exception as exc:
            logger.error(
                "[%s] Failed to process display name results: %s", tenant_id[:8], exc
            )
            await db.rollback()


async def _process_delegation_results(
    tenant_id: str,
    delegated: List[str],
    failed: List[Dict[str, str]],
    error: str | None,
):
    """Process delegation results."""

    async with SessionLocal() as db:
        try:
            for email in delegated:
                await db.execute(
                    update(Mailbox)
                    .where(Mailbox.email == email)
                    .values(delegation_done=True)
                )

            all_done = len(failed) == 0
            await db.execute(
                update(Tenant)
                .where(Tenant.id == tenant_id)
                .values(
                    step6_delegations_done=all_done,
                    delegation_completed=all_done,
                )
            )

            if all_done:
                await db.execute(
                    update(Tenant)
                    .where(Tenant.id == tenant_id)
                    .values(
                        step6_complete=True,
                        status="ready",
                    )
                )

            await db.commit()
            logger.info("[%s] Delegation results processed", tenant_id[:8])

        except Exception as exc:
            logger.error(
                "[%s] Failed to process delegation results: %s", tenant_id[:8], exc
            )
            await db.rollback()