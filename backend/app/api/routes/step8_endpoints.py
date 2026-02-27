# =============================================================================
# STEP 8: INSTANTLY UPLOAD ENDPOINTS
# =============================================================================
"""
Step 8 endpoints for uploading mailboxes to Instantly.ai via OAuth automation
and CRUD for Instantly account management.
"""

import logging
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session as get_db
from app.models.batch import SetupBatch
from app.models.mailbox import Mailbox

router = APIRouter(prefix="/api/v1/step8", tags=["step8-upload"])
logger = logging.getLogger(__name__)

# In-memory job tracking for step8 uploads
step8_jobs = {}


# Step 8 Schemas
class Step8StartRequest(BaseModel):
    """Request for starting Step 8 upload."""
    instantly_email: str
    instantly_password: str
    num_workers: int = 3  # 1-5 parallel browsers
    headless: bool = True  # Headless mode for Railway
    skip_uploaded: bool = True  # Skip already-uploaded mailboxes


# STEP 8 ENDPOINTS

@router.get("/batches/{batch_id}/step8/status")
async def get_step8_status(
    batch_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get Step 8 (Instantly Upload) status for batch.

    Returns:
    - Mailbox counts (total, uploaded, failed, pending)
    - Instantly configuration from batch
    - Job status if upload is in progress
    """
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")

    # Count mailboxes
    mailboxes_total = await db.scalar(
        select(func.count(Mailbox.id)).where(Mailbox.batch_id == batch_id)
    ) or 0

    mailboxes_uploaded = await db.scalar(
        select(func.count(Mailbox.id)).where(
            Mailbox.batch_id == batch_id,
            Mailbox.instantly_uploaded == True
        )
    ) or 0

    mailboxes_failed = await db.scalar(
        select(func.count(Mailbox.id)).where(
            Mailbox.batch_id == batch_id,
            Mailbox.instantly_uploaded == False,
            Mailbox.instantly_upload_error.isnot(None)
        )
    ) or 0

    mailboxes_pending = mailboxes_total - mailboxes_uploaded - mailboxes_failed

    # Get job status if running
    job_id = str(batch_id)
    job_status = step8_jobs.get(job_id, {})

    return {
        "batch_id": str(batch_id),
        "batch_name": batch.name,
        "instantly_email": getattr(batch, "instantly_email", None),
        "summary": {
            "total": mailboxes_total,
            "uploaded": mailboxes_uploaded,
            "failed": mailboxes_failed,
            "pending": mailboxes_pending,
        },
        "job": job_status if job_status else None,
    }


@router.post("/batches/{batch_id}/step8/start")
async def start_step8_upload(
    batch_id: UUID,
    request: Step8StartRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Start Step 8: Upload mailboxes to Instantly.ai.

    This runs Selenium automation to:
    1. Log into Instantly.ai
    2. For each mailbox, trigger Microsoft OAuth
    3. Handle OAuth popup (email/password/consent)
    4. Track uploaded mailboxes in DB

    Supports:
    - Multi-browser parallel processing (1-5 workers)
    - Automatic retry (up to 2 retries per failed mailbox)
    - Resume capability (skip already-uploaded mailboxes)
    - Headless mode for Railway deployment
    """
    # Validate num_workers
    if request.num_workers < 1 or request.num_workers > 5:
        raise HTTPException(400, "num_workers must be between 1 and 5")

    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")

    # Check if upload already in progress
    job_id = str(batch_id)
    if job_id in step8_jobs and step8_jobs[job_id].get("status") == "running":
        return {
            "success": False,
            "message": "Upload already in progress for this batch",
            "job_id": job_id,
            "started_at": step8_jobs[job_id].get("started_at")
        }

    # Count eligible mailboxes
    mailboxes_query = select(func.count(Mailbox.id)).where(Mailbox.batch_id == batch_id)
    if request.skip_uploaded:
        mailboxes_query = mailboxes_query.where(Mailbox.instantly_uploaded == False)

    eligible_count = await db.scalar(mailboxes_query) or 0

    if eligible_count == 0:
        return {
            "success": False,
            "message": "No mailboxes to upload (all already uploaded or none exist)",
            "eligible_count": 0
        }

    # Save Instantly credentials to batch
    batch.instantly_email = request.instantly_email
    # Note: instantly_api_key is saved in batch but password is not persisted
    await db.commit()

    # Initialize job tracking
    step8_jobs[job_id] = {
        "status": "running",
        "batch_id": str(batch_id),
        "batch_name": batch.name,
        "started_at": datetime.utcnow().isoformat(),
        "completed_at": None,
        "total": eligible_count,
        "uploaded": 0,
        "failed": 0,
        "skipped": 0,
        "current_mailbox": None,
        "error": None,
        "num_workers": request.num_workers,
        "headless": request.headless,
        "errors": []
    }

    # Run in background
    async def run_upload():
        try:
            from app.services.instantly_uploader import run_instantly_upload_for_batch

            summary = await run_instantly_upload_for_batch(
                batch_id=batch_id,
                instantly_email=request.instantly_email,
                instantly_password=request.instantly_password,
                num_workers=request.num_workers,
                headless=request.headless,
                skip_uploaded=request.skip_uploaded
            )

            step8_jobs[job_id]["status"] = "completed"
            step8_jobs[job_id]["uploaded"] = summary["uploaded"]
            step8_jobs[job_id]["failed"] = summary["failed"]
            step8_jobs[job_id]["skipped"] = summary.get("skipped", 0)
            step8_jobs[job_id]["errors"] = summary.get("errors", [])
            step8_jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()

            logger.info(f"Step 8 upload completed for batch {batch_id}: {summary['uploaded']}/{summary['total']} uploaded")

        except Exception as e:
            step8_jobs[job_id]["status"] = "failed"
            step8_jobs[job_id]["error"] = str(e)
            step8_jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()
            logger.error(f"Step 8 upload failed for batch {batch_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())

    background_tasks.add_task(run_upload)

    logger.info(f"Step 8 upload started for batch {batch_id}: {eligible_count} mailboxes, {request.num_workers} workers")

    return {
        "success": True,
        "message": f"Started Instantly upload for {eligible_count} mailbox(es)",
        "job_id": job_id,
        "eligible_count": eligible_count,
        "num_workers": request.num_workers,
        "headless": request.headless,
        "skip_uploaded": request.skip_uploaded,
        "estimated_minutes": round(eligible_count / request.num_workers * 0.5)  # ~30s per mailbox
    }


@router.post("/batches/{batch_id}/step8/retry-failed")
async def retry_step8_failed(
    batch_id: UUID,
    request: Step8StartRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Retry Step 8 upload for failed mailboxes only.

    Resets error state for failed mailboxes and reruns upload.
    """
    batch = await db.get(SetupBatch, batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")

    # Find failed mailboxes
    failed_result = await db.execute(
        select(Mailbox).where(
            Mailbox.batch_id == batch_id,
            Mailbox.instantly_uploaded == False,
            Mailbox.instantly_upload_error.isnot(None)
        )
    )
    failed_mailboxes = failed_result.scalars().all()

    if not failed_mailboxes:
        return {
            "success": False,
            "message": "No failed mailboxes to retry",
            "failed_count": 0
        }

    # Clear errors
    for mailbox in failed_mailboxes:
        mailbox.instantly_upload_error = None
    await db.commit()

    logger.info(f"Retrying Step 8 for {len(failed_mailboxes)} failed mailboxes in batch {batch_id}")

    # Use same start logic but with skip_uploaded=True to only process these
    request.skip_uploaded = True
    return await start_step8_upload(batch_id, request, background_tasks, db)


# =============================================================================
# INSTANTLY ACCOUNT CRUD ENDPOINTS
# =============================================================================

class InstantlyAccountCreate(BaseModel):
    """Schema for creating Instantly account."""
    label: str
    email: str
    password: str
    api_key: Optional[str] = None
    is_default: bool = False


class InstantlyAccountUpdate(BaseModel):
    """Schema for updating Instantly account."""
    label: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    api_key: Optional[str] = None
    is_default: Optional[bool] = None


@router.get("/instantly/accounts")
async def list_instantly_accounts(db: AsyncSession = Depends(get_db)):
    """List all saved Instantly accounts (passwords hidden)."""
    from app.models.instantly_account import InstantlyAccount

    result = await db.execute(
        select(InstantlyAccount).order_by(InstantlyAccount.is_default.desc(), InstantlyAccount.created_at.desc())
    )
    accounts = result.scalars().all()

    return {
        "accounts": [
            {
                "id": str(acc.id),
                "label": acc.label,
                "email": acc.email,
                "has_api_key": bool(acc.api_key),
                "is_default": acc.is_default,
                "created_at": acc.created_at.isoformat(),
                "last_used_at": acc.last_used_at.isoformat() if acc.last_used_at else None,
            }
            for acc in accounts
        ]
    }


@router.post("/instantly/accounts")
async def create_instantly_account(
    request: InstantlyAccountCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create new Instantly account.

    If is_default=True, removes default flag from other accounts.
    """
    from app.models.instantly_account import InstantlyAccount

    # Check for duplicate email
    existing = await db.execute(
        select(InstantlyAccount).where(InstantlyAccount.email == request.email)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Account with this email already exists")

    # If setting as default, remove default from others
    if request.is_default:
        await db.execute(
            update(InstantlyAccount).values(is_default=False)
        )

    account = InstantlyAccount(
        label=request.label,
        email=request.email,
        password=request.password,
        api_key=request.api_key,
        is_default=request.is_default
    )

    db.add(account)
    await db.commit()
    await db.refresh(account)

    logger.info(f"Created Instantly account: {request.label} ({request.email})")

    return {
        "success": True,
        "message": f"Created Instantly account '{request.label}'",
        "account": {
            "id": str(account.id),
            "label": account.label,
            "email": account.email,
            "is_default": account.is_default
        }
    }


@router.put("/instantly/accounts/{account_id}")
async def update_instantly_account(
    account_id: UUID,
    request: InstantlyAccountUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update Instantly account."""
    from app.models.instantly_account import InstantlyAccount

    account = await db.get(InstantlyAccount, account_id)
    if not account:
        raise HTTPException(404, "Account not found")

    # If setting as default, remove default from others
    if request.is_default is True and not account.is_default:
        await db.execute(
            update(InstantlyAccount).where(InstantlyAccount.id != account_id).values(is_default=False)
        )

    # Update fields
    if request.label is not None:
        account.label = request.label
    if request.email is not None:
        account.email = request.email
    if request.password is not None:
        account.password = request.password
    if request.api_key is not None:
        account.api_key = request.api_key
    if request.is_default is not None:
        account.is_default = request.is_default

    account.updated_at = datetime.utcnow()
    await db.commit()

    return {
        "success": True,
        "message": f"Updated account '{account.label}'",
        "account": {
            "id": str(account.id),
            "label": account.label,
            "email": account.email,
            "is_default": account.is_default
        }
    }


@router.delete("/instantly/accounts/{account_id}")
async def delete_instantly_account(
    account_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Delete Instantly account."""
    from app.models.instantly_account import InstantlyAccount

    account = await db.get(InstantlyAccount, account_id)
    if not account:
        raise HTTPException(404, "Account not found")

    label = account.label
    await db.delete(account)
    await db.commit()

    logger.info(f"Deleted Instantly account: {label}")

    return {
        "success": True,
        "message": f"Deleted account '{label}'"
    }


# =============================================================================
# STANDALONE INSTANTLY UPLOAD ENDPOINTS
# =============================================================================

@router.get("/instantly/batches-for-upload")
async def get_batches_for_upload(db: AsyncSession = Depends(get_db)):
    """Get list of batches with mailboxes available for Instantly upload.

    Used by the standalone /instantly-upload page to select batches.
    """
    result = await db.execute(
        select(SetupBatch).order_by(SetupBatch.created_at.desc())
    )
    batches = result.scalars().all()

    batch_list = []
    for batch in batches:
        # Count mailboxes
        total = await db.scalar(
            select(func.count(Mailbox.id)).where(Mailbox.batch_id == batch.id)
        ) or 0

        uploaded = await db.scalar(
            select(func.count(Mailbox.id)).where(
                Mailbox.batch_id == batch.id,
                Mailbox.instantly_uploaded == True
            )
        ) or 0

        failed = await db.scalar(
            select(func.count(Mailbox.id)).where(
                Mailbox.batch_id == batch.id,
                Mailbox.instantly_uploaded == False,
                Mailbox.instantly_upload_error.isnot(None)
            )
        ) or 0

        if total > 0:  # Only include batches with mailboxes
            batch_list.append({
                "id": str(batch.id),
                "name": batch.name,
                "current_step": batch.current_step,
                "status": batch.status.value,
                "mailboxes": {
                    "total": total,
                    "uploaded": uploaded,
                    "failed": failed,
                    "pending": total - uploaded - failed
                },
                "instantly_email": getattr(batch, "instantly_email", None)
            })

    return {"batches": batch_list}


class MultiUploadRequest(BaseModel):
    """Request for uploading multiple batches."""
    batch_ids: List[UUID]
    instantly_email: str
    instantly_password: str
    num_workers: int = 3
    headless: bool = True
    skip_uploaded: bool = True


@router.post("/instantly/upload-multiple")
async def upload_multiple_batches(
    request: MultiUploadRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """Upload mailboxes from multiple batches to Instantly.ai.

    Processes all selected batches sequentially with the same Instantly credentials.
    Useful for bulk operations on the standalone upload page.
    """
    if not request.batch_ids:
        raise HTTPException(400, "No batch IDs provided")

    if request.num_workers < 1 or request.num_workers > 5:
        raise HTTPException(400, "num_workers must be between 1 and 5")

    # Verify all batches exist
    for batch_id in request.batch_ids:
        batch = await db.get(SetupBatch, batch_id)
        if not batch:
            raise HTTPException(404, f"Batch {batch_id} not found")

    # Count total mailboxes across all batches
    total_mailboxes = 0
    for batch_id in request.batch_ids:
        count_query = select(func.count(Mailbox.id)).where(Mailbox.batch_id == batch_id)
        if request.skip_uploaded:
            count_query = count_query.where(Mailbox.instantly_uploaded == False)
        count = await db.scalar(count_query) or 0
        total_mailboxes += count

    if total_mailboxes == 0:
        return {
            "success": False,
            "message": "No mailboxes to upload across selected batches",
            "total_mailboxes": 0
        }

    job_id = f"multi_{datetime.utcnow().timestamp()}"

    # Initialize job tracking
    step8_jobs[job_id] = {
        "status": "running",
        "type": "multi_batch",
        "batch_ids": [str(bid) for bid in request.batch_ids],
        "started_at": datetime.utcnow().isoformat(),
        "completed_at": None,
        "total": total_mailboxes,
        "uploaded": 0,
        "failed": 0,
        "skipped": 0,
        "current_batch": None,
        "error": None,
        "batch_results": []
    }

    # Run in background
    async def run_multi_upload():
        try:
            from app.services.instantly_uploader import run_instantly_upload_for_batch

            for batch_id in request.batch_ids:
                step8_jobs[job_id]["current_batch"] = str(batch_id)

                summary = await run_instantly_upload_for_batch(
                    batch_id=batch_id,
                    instantly_email=request.instantly_email,
                    instantly_password=request.instantly_password,
                    num_workers=request.num_workers,
                    headless=request.headless,
                    skip_uploaded=request.skip_uploaded
                )

                step8_jobs[job_id]["uploaded"] += summary["uploaded"]
                step8_jobs[job_id]["failed"] += summary["failed"]
                step8_jobs[job_id]["skipped"] += summary.get("skipped", 0)
                step8_jobs[job_id]["batch_results"].append({
                    "batch_id": str(batch_id),
                    "summary": summary
                })

            step8_jobs[job_id]["status"] = "completed"
            step8_jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()

        except Exception as e:
            step8_jobs[job_id]["status"] = "failed"
            step8_jobs[job_id]["error"] = str(e)
            step8_jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()

    background_tasks.add_task(run_multi_upload)

    return {
        "success": True,
        "job_id": job_id,
        "message": f"Started multi-batch upload for {len(request.batch_ids)} batch(es)",
        "total_mailboxes": total_mailboxes,
        "batch_count": len(request.batch_ids)
    }


@router.get("/instantly/upload-status/{job_id}")
async def get_upload_status(job_id: str):
    """Get status of an Instantly upload job (single or multi-batch)."""
    if job_id not in step8_jobs:
        return {
            "status": "not_found",
            "message": "Upload job not found"
        }

    return step8_jobs[job_id]
