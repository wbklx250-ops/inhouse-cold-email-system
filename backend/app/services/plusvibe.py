"""
PlusVibe.ai — mailbox upload via Microsoft OAuth (same flow pattern as Smartlead).

Uses the OAuth connect URL from the PlusVibe dashboard; no REST client is wired
yet, so duplicate skip / post-upload API tuning are not available.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict

from sqlalchemy import select, update

from app.services.microsoft_sequencer_oauth import MicrosoftSequencerOAuthUploader

logger = logging.getLogger("plusvibe")


class PlusVibeOAuthUploader(MicrosoftSequencerOAuthUploader):
    def __init__(self, headless: bool = True, worker_id: int = 0):
        super().__init__(
            headless=headless,
            worker_id=worker_id,
            success_url_markers=("plusvibe", "plusvibe.ai", "app.plusvibe"),
            screenshot_prefix="pv",
        )


def process_plusvibe_mailbox_sync(
    uploader: PlusVibeOAuthUploader,
    mailbox_data: Dict[str, Any],
    oauth_url: str,
    max_retries: int = 2,
) -> Dict[str, Any]:
    mailbox_id = mailbox_data["id"]
    email = mailbox_data["email"]
    password = mailbox_data["password"]

    for attempt in range(max_retries + 1):
        try:
            success = uploader.upload_account(email, password, oauth_url)
            if success:
                return {
                    "mailbox_id": mailbox_id,
                    "success": True,
                    "error": None,
                    "retries": attempt,
                }
            if attempt < max_retries:
                logger.warning(
                    f"[Worker {uploader.worker_id}] Attempt {attempt + 1} failed for {email}, retrying..."
                )
                time.sleep(3)
            else:
                return {
                    "mailbox_id": mailbox_id,
                    "success": False,
                    "error": "OAuth upload failed after retries",
                    "retries": attempt,
                }
        except Exception as e:
            if attempt < max_retries:
                time.sleep(3)
            else:
                return {
                    "mailbox_id": mailbox_id,
                    "success": False,
                    "error": str(e),
                    "retries": attempt,
                }

    return {"mailbox_id": mailbox_id, "success": False, "error": "Unknown error", "retries": max_retries}


async def run_plusvibe_upload_for_batch(
    batch_id: str,
    oauth_url: str,
    num_workers: int = 3,
    headless: bool = True,
    skip_uploaded: bool = True,
) -> Dict[str, Any]:
    from app.models.mailbox import Mailbox
    from app.models.tenant import Tenant
    from app.models.batch import SetupBatch
    from app.db.session import async_session_factory

    logger.info(f"Starting PlusVibe upload for batch {batch_id} with {num_workers} workers")

    async with async_session_factory() as session:
        batch_result = await session.execute(select(SetupBatch).where(SetupBatch.id == batch_id))
        batch = batch_result.scalar_one_or_none()
        if not batch:
            return {"error": "Batch not found", "total": 0, "uploaded": 0, "failed": 0, "skipped": 0}

        query = (
            select(Mailbox)
            .join(Tenant, Mailbox.tenant_id == Tenant.id)
            .where(Tenant.batch_id == batch_id)
        )
        if skip_uploaded:
            query = query.where(Mailbox.plusvibe_uploaded == False)

        result = await session.execute(query)
        mailboxes = result.scalars().all()

        if not mailboxes:
            logger.info(f"No mailboxes to upload for batch {batch_id}")
            return {"total": 0, "uploaded": 0, "failed": 0, "skipped": 0, "errors": []}

        mailbox_list = [
            {
                "id": str(mb.id),
                "email": mb.email,
                "password": mb.initial_password or mb.password or "#Sendemails1",
            }
            for mb in mailboxes
        ]

    logger.info(f"Found {len(mailbox_list)} mailboxes to upload to PlusVibe")

    uploaded_count = 0
    failed_count = 0
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        uploaders = [PlusVibeOAuthUploader(headless=headless, worker_id=i) for i in range(num_workers)]

        try:
            futures = []
            for i, mailbox_data in enumerate(mailbox_list):
                uploader = uploaders[i % len(uploaders)]
                futures.append(
                    executor.submit(process_plusvibe_mailbox_sync, uploader, mailbox_data, oauth_url)
                )

            for future in as_completed(futures):
                result = future.result()

                async with async_session_factory() as session:
                    if result["success"]:
                        await session.execute(
                            update(Mailbox)
                            .where(Mailbox.id == result["mailbox_id"])
                            .values(
                                plusvibe_uploaded=True,
                                plusvibe_uploaded_at=datetime.utcnow(),
                                plusvibe_upload_error=None,
                            )
                        )
                        uploaded_count += 1
                    else:
                        await session.execute(
                            update(Mailbox)
                            .where(Mailbox.id == result["mailbox_id"])
                            .values(
                                plusvibe_uploaded=False,
                                plusvibe_upload_error=result["error"],
                            )
                        )
                        failed_count += 1
                        if result.get("error"):
                            errors.append(result["error"])

                    await session.commit()

                logger.info(f"Progress: {uploaded_count + failed_count}/{len(mailbox_list)} processed")

        finally:
            pass

    logger.info(
        f"PlusVibe upload complete: {uploaded_count} uploaded, {failed_count} failed for batch {batch_id}"
    )

    return {
        "total": len(mailbox_list),
        "uploaded": uploaded_count,
        "failed": failed_count,
        "skipped": 0,
        "errors": errors[:10],
    }
