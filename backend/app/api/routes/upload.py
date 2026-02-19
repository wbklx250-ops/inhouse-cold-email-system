"""
Upload Management Routes — Cross-batch mailbox upload tracking.

Provides a dedicated API for managing sequencer uploads across ALL batches.
This replaces the batch-level upload toggle with mailbox-level granularity.
"""
import csv
import io
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, func, select, case, distinct
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db_session as get_db
from app.models.mailbox import Mailbox, MailboxStatus
from app.models.tenant import Tenant
from app.models.domain import Domain
from app.models.batch import SetupBatch

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/upload", tags=["upload"])


# ============================================================================
# Schemas
# ============================================================================

class UploadDashboardStats(BaseModel):
    """Top-level stats for the upload dashboard."""
    total_mailboxes: int
    total_ready: int          # setup_complete=True (eligible for upload)
    total_uploaded: int       # uploaded_to_sequencer=True
    total_pending: int        # setup_complete=True AND uploaded_to_sequencer=False
    total_errored: int        # has upload_error set
    total_not_ready: int      # setup_complete=False (still in setup pipeline)
    batches_with_pending: int # number of batches that have pending mailboxes


class BatchUploadSummary(BaseModel):
    """Upload summary per batch."""
    batch_id: UUID
    batch_name: str
    batch_status: str
    total_mailboxes: int
    ready: int
    uploaded: int
    pending: int
    errored: int
    not_ready: int
    created_at: str


class MailboxUploadItem(BaseModel):
    """Single mailbox in the upload list."""
    id: UUID
    email: str
    display_name: str
    password: str | None = None
    tenant_id: UUID
    tenant_name: str | None = None
    domain_name: str | None = None
    batch_id: UUID | None = None
    batch_name: str | None = None
    status: str
    setup_complete: bool
    uploaded_to_sequencer: bool
    uploaded_at: str | None = None
    sequencer_name: str | None = None
    upload_error: str | None = None

    class Config:
        from_attributes = True


class MailboxUploadList(BaseModel):
    """Paginated list of mailboxes for upload management."""
    items: list[MailboxUploadItem]
    total: int
    page: int
    per_page: int
    # Summary counts for the current filter
    filter_ready: int
    filter_uploaded: int
    filter_pending: int


class BulkMarkUploadedRequest(BaseModel):
    """Request to mark multiple mailboxes as uploaded."""
    mailbox_ids: list[UUID]
    sequencer_name: str = "instantly"  # Default sequencer


class BulkMarkUploadedResponse(BaseModel):
    """Response from bulk mark-as-uploaded."""
    success: bool
    marked_count: int
    already_uploaded: int
    not_ready: int
    errors: list[str]


class BulkUnmarkRequest(BaseModel):
    """Request to unmark mailboxes."""
    mailbox_ids: list[UUID]


# ============================================================================
# DASHBOARD — Cross-batch overview
# ============================================================================

@router.get("/dashboard", response_model=UploadDashboardStats)
async def get_upload_dashboard(db: AsyncSession = Depends(get_db)):
    """
    Get cross-batch upload dashboard statistics.

    Returns total counts across ALL batches for:
    - Total mailboxes in the system
    - Ready for upload (setup_complete=True)
    - Already uploaded
    - Pending upload (ready but not uploaded)
    - Not ready (still in setup pipeline)
    """
    # Single query with conditional aggregation
    result = await db.execute(
        select(
            func.count(Mailbox.id).label("total"),
            func.count(case((Mailbox.setup_complete == True, 1))).label("ready"),
            func.count(case((Mailbox.uploaded_to_sequencer == True, 1))).label("uploaded"),
            func.count(case((
                and_(Mailbox.setup_complete == True, Mailbox.uploaded_to_sequencer == False),
                1
            ))).label("pending"),
            func.count(case((Mailbox.upload_error.isnot(None), 1))).label("errored"),
            func.count(case((Mailbox.setup_complete == False, 1))).label("not_ready"),
        )
    )
    row = result.one()

    # Count batches with pending mailboxes
    batches_pending = await db.execute(
        select(func.count(distinct(Mailbox.batch_id))).where(
            and_(
                Mailbox.setup_complete == True,
                Mailbox.uploaded_to_sequencer == False,
                Mailbox.batch_id.isnot(None),
            )
        )
    )

    return UploadDashboardStats(
        total_mailboxes=row.total,
        total_ready=row.ready,
        total_uploaded=row.uploaded,
        total_pending=row.pending,
        total_errored=row.errored,
        total_not_ready=row.not_ready,
        batches_with_pending=batches_pending.scalar() or 0,
    )


# ============================================================================
# BATCH SUMMARIES — Per-batch breakdown
# ============================================================================

@router.get("/batches", response_model=list[BatchUploadSummary])
async def get_batch_upload_summaries(
    only_with_pending: bool = Query(False, description="Only show batches that have pending uploads"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get upload summary for each batch.

    Shows how many mailboxes in each batch are ready, uploaded, pending, etc.
    """
    # Get all batches
    batch_query = select(SetupBatch).order_by(SetupBatch.created_at.desc())
    batches_result = await db.execute(batch_query)
    batches = batches_result.scalars().all()

    summaries = []
    for batch in batches:
        # Get mailbox counts for this batch
        counts = await db.execute(
            select(
                func.count(Mailbox.id).label("total"),
                func.count(case((Mailbox.setup_complete == True, 1))).label("ready"),
                func.count(case((Mailbox.uploaded_to_sequencer == True, 1))).label("uploaded"),
                func.count(case((
                    and_(Mailbox.setup_complete == True, Mailbox.uploaded_to_sequencer == False),
                    1
                ))).label("pending"),
                func.count(case((Mailbox.upload_error.isnot(None), 1))).label("errored"),
                func.count(case((Mailbox.setup_complete == False, 1))).label("not_ready"),
            ).where(Mailbox.batch_id == batch.id)
        )
        row = counts.one()

        if only_with_pending and row.pending == 0:
            continue

        summaries.append(BatchUploadSummary(
            batch_id=batch.id,
            batch_name=batch.name,
            batch_status=batch.status.value,
            total_mailboxes=row.total,
            ready=row.ready,
            uploaded=row.uploaded,
            pending=row.pending,
            errored=row.errored,
            not_ready=row.not_ready,
            created_at=batch.created_at.isoformat(),
        ))

    return summaries


# ============================================================================
# MAILBOX LIST — Filterable, paginated, cross-batch
# ============================================================================

@router.get("/mailboxes", response_model=MailboxUploadList)
async def list_mailboxes_for_upload(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=500),
    batch_id: Optional[UUID] = Query(None, description="Filter by batch"),
    tenant_id: Optional[UUID] = Query(None, description="Filter by tenant"),
    upload_status: Optional[str] = Query(None, description="Filter: 'pending', 'uploaded', 'errored', 'not_ready', 'all'"),
    search: Optional[str] = Query(None, description="Search by email"),
    sequencer_name: Optional[str] = Query(None, description="Filter by sequencer name"),
    db: AsyncSession = Depends(get_db),
):
    """
    List mailboxes for upload management with filtering and pagination.

    Default filter: only shows 'pending' mailboxes (ready but not uploaded).
    """
    # Base filters
    base_filter = []

    if batch_id:
        base_filter.append(Mailbox.batch_id == batch_id)
    if tenant_id:
        base_filter.append(Mailbox.tenant_id == tenant_id)
    if search:
        base_filter.append(Mailbox.email.ilike(f"%{search}%"))
    if sequencer_name:
        base_filter.append(Mailbox.sequencer_name == sequencer_name)

    # Upload status filter
    if upload_status == "pending" or upload_status is None:
        base_filter.append(Mailbox.setup_complete == True)
        base_filter.append(Mailbox.uploaded_to_sequencer == False)
    elif upload_status == "uploaded":
        base_filter.append(Mailbox.uploaded_to_sequencer == True)
    elif upload_status == "errored":
        base_filter.append(Mailbox.upload_error.isnot(None))
    elif upload_status == "not_ready":
        base_filter.append(Mailbox.setup_complete == False)
    # "all" = no additional filter

    # Count total matching
    if base_filter:
        count_query = select(func.count(Mailbox.id)).where(and_(*base_filter))
    else:
        count_query = select(func.count(Mailbox.id))
    total = (await db.execute(count_query)).scalar() or 0

    # Get summary counts for the base filters (minus upload_status)
    count_base = []
    if batch_id:
        count_base.append(Mailbox.batch_id == batch_id)
    if tenant_id:
        count_base.append(Mailbox.tenant_id == tenant_id)
    if search:
        count_base.append(Mailbox.email.ilike(f"%{search}%"))

    summary_select = select(
        func.count(case((Mailbox.setup_complete == True, 1))).label("ready"),
        func.count(case((Mailbox.uploaded_to_sequencer == True, 1))).label("uploaded"),
        func.count(case((
            and_(Mailbox.setup_complete == True, Mailbox.uploaded_to_sequencer == False),
            1
        ))).label("pending"),
    )
    if count_base:
        summary_select = summary_select.where(and_(*count_base))

    summary_result = await db.execute(summary_select)
    summary_row = summary_result.one()

    # Fetch mailboxes with tenant info
    offset = (page - 1) * per_page
    query = select(Mailbox).options(selectinload(Mailbox.tenant))
    if base_filter:
        query = query.where(and_(*base_filter))
    query = query.order_by(Mailbox.email).offset(offset).limit(per_page)

    result = await db.execute(query)
    mailboxes = result.scalars().all()

    # Build response items with tenant/batch info
    items = []
    batch_cache: dict[UUID, str | None] = {}

    for mb in mailboxes:
        # Get batch name (cached)
        batch_name = None
        if mb.batch_id:
            if mb.batch_id not in batch_cache:
                batch = await db.get(SetupBatch, mb.batch_id)
                batch_cache[mb.batch_id] = batch.name if batch else None
            batch_name = batch_cache[mb.batch_id]

        # Get domain from email
        domain_name = mb.email.split("@")[1] if "@" in mb.email else None

        # Get tenant name
        tenant_name = None
        if mb.tenant:
            tenant_name = mb.tenant.name or mb.tenant.onmicrosoft_domain

        items.append(MailboxUploadItem(
            id=mb.id,
            email=mb.email,
            display_name=mb.display_name,
            tenant_id=mb.tenant_id,
            tenant_name=tenant_name,
            domain_name=domain_name,
            batch_id=mb.batch_id,
            batch_name=batch_name,
            status=mb.status.value,
            setup_complete=mb.setup_complete,
            uploaded_to_sequencer=mb.uploaded_to_sequencer,
            uploaded_at=mb.uploaded_at.isoformat() if mb.uploaded_at else None,
            sequencer_name=mb.sequencer_name,
            upload_error=mb.upload_error,
        ))

    return MailboxUploadList(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        filter_ready=summary_row.ready,
        filter_uploaded=summary_row.uploaded,
        filter_pending=summary_row.pending,
    )


# ============================================================================
# BULK MARK AS UPLOADED
# ============================================================================

@router.post("/mark-uploaded", response_model=BulkMarkUploadedResponse)
async def bulk_mark_uploaded(
    request: BulkMarkUploadedRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Mark multiple mailboxes as uploaded to a sequencer.

    Only marks mailboxes that are:
    - setup_complete=True (ready for upload)
    - uploaded_to_sequencer=False (not already uploaded)
    """
    marked = 0
    already_uploaded = 0
    not_ready = 0
    errors = []
    now = datetime.utcnow()

    for mb_id in request.mailbox_ids:
        mb = await db.get(Mailbox, mb_id)
        if not mb:
            errors.append(f"Mailbox {mb_id} not found")
            continue

        if mb.uploaded_to_sequencer:
            already_uploaded += 1
            continue

        if not mb.setup_complete:
            not_ready += 1
            continue

        mb.uploaded_to_sequencer = True
        mb.uploaded_at = now
        mb.sequencer_name = request.sequencer_name
        mb.upload_error = None  # Clear any previous error
        marked += 1

    await db.commit()

    logger.info(f"Bulk mark uploaded: {marked} marked, {already_uploaded} already uploaded, {not_ready} not ready")

    return BulkMarkUploadedResponse(
        success=True,
        marked_count=marked,
        already_uploaded=already_uploaded,
        not_ready=not_ready,
        errors=errors,
    )


# ============================================================================
# MARK ALL PENDING AS UPLOADED (One-click for entire batch or all)
# ============================================================================

@router.post("/mark-all-pending")
async def mark_all_pending_uploaded(
    sequencer_name: str = Query("instantly"),
    batch_id: Optional[UUID] = Query(None, description="Limit to specific batch, or all if not provided"),
    db: AsyncSession = Depends(get_db),
):
    """
    Mark ALL pending mailboxes as uploaded in one click.

    Pending = setup_complete=True AND uploaded_to_sequencer=False.
    Optionally filter by batch_id to mark only one batch's pending mailboxes.
    """
    now = datetime.utcnow()

    filters = [
        Mailbox.setup_complete == True,
        Mailbox.uploaded_to_sequencer == False,
    ]
    if batch_id:
        filters.append(Mailbox.batch_id == batch_id)

    # Get matching mailboxes
    result = await db.execute(select(Mailbox).where(and_(*filters)))
    mailboxes = result.scalars().all()

    count = 0
    for mb in mailboxes:
        mb.uploaded_to_sequencer = True
        mb.uploaded_at = now
        mb.sequencer_name = sequencer_name
        mb.upload_error = None
        count += 1

    await db.commit()

    # Also update the batch-level flag if batch_id specified
    if batch_id:
        batch = await db.get(SetupBatch, batch_id)
        if batch:
            batch.uploaded_to_sequencer = True
            batch.uploaded_at = now
            await db.commit()

    logger.info(f"Marked {count} pending mailboxes as uploaded to {sequencer_name}" +
                (f" in batch {batch_id}" if batch_id else " across all batches"))

    return {
        "success": True,
        "marked_count": count,
        "sequencer_name": sequencer_name,
        "batch_id": str(batch_id) if batch_id else None,
    }


# ============================================================================
# UNMARK (undo upload marking)
# ============================================================================

@router.post("/unmark")
async def bulk_unmark_uploaded(
    request: BulkUnmarkRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Remove upload marking from mailboxes. Useful for re-uploading.
    """
    unmarked = 0
    for mb_id in request.mailbox_ids:
        mb = await db.get(Mailbox, mb_id)
        if not mb:
            continue
        if mb.uploaded_to_sequencer:
            mb.uploaded_to_sequencer = False
            mb.uploaded_at = None
            mb.sequencer_name = None
            mb.upload_error = None
            unmarked += 1

    await db.commit()

    return {"success": True, "unmarked_count": unmarked}


# ============================================================================
# EXPORT PENDING CSV — Only un-uploaded, ready mailboxes
# ============================================================================

@router.get("/export-pending")
async def export_pending_csv(
    batch_id: Optional[UUID] = Query(None, description="Filter by batch"),
    sequencer_format: str = Query("instantly", description="Format: 'instantly', 'plusvibe', 'smartlead', 'generic'"),
    db: AsyncSession = Depends(get_db),
):
    """
    Export only PENDING (ready but not uploaded) mailboxes as CSV.

    This is the smart export — only gives you mailboxes you haven't uploaded yet.
    Format adapts to the target sequencer.
    """
    filters = [
        Mailbox.setup_complete == True,
        Mailbox.uploaded_to_sequencer == False,
    ]
    if batch_id:
        filters.append(Mailbox.batch_id == batch_id)

    result = await db.execute(
        select(Mailbox)
        .options(selectinload(Mailbox.tenant))
        .where(and_(*filters))
        .order_by(Mailbox.email)
    )
    mailboxes = result.scalars().all()

    if not mailboxes:
        raise HTTPException(status_code=404, detail="No pending mailboxes found")

    # Build CSV based on format
    output = io.StringIO()

    if sequencer_format == "instantly":
        writer = csv.writer(output)
        writer.writerow(["first_name", "last_name", "email", "password", "smtp_host", "smtp_port", "smtp_username", "imap_host", "imap_port", "imap_username", "warmup_enabled", "warmup_limit"])
        for mb in mailboxes:
            parts = mb.display_name.split(" ", 1)
            first = parts[0] if parts else mb.display_name
            last = parts[1] if len(parts) > 1 else ""
            writer.writerow([
                first, last, mb.email, mb.password or "",
                "smtp.office365.com", "587", mb.email,
                "outlook.office365.com", "993", mb.email,
                "true", "2",
            ])
    elif sequencer_format == "plusvibe":
        writer = csv.writer(output)
        writer.writerow(["email", "password", "first_name", "last_name", "smtp_host", "smtp_port", "imap_host", "imap_port"])
        for mb in mailboxes:
            parts = mb.display_name.split(" ", 1)
            first = parts[0] if parts else mb.display_name
            last = parts[1] if len(parts) > 1 else ""
            writer.writerow([
                mb.email, mb.password or "", first, last,
                "smtp.office365.com", "587",
                "outlook.office365.com", "993",
            ])
    elif sequencer_format == "smartlead":
        writer = csv.writer(output)
        writer.writerow(["from_email", "from_name", "smtp_host", "smtp_port", "smtp_username", "smtp_password", "imap_host", "imap_port", "imap_username", "imap_password", "warmup_enabled"])
        for mb in mailboxes:
            writer.writerow([
                mb.email, mb.display_name,
                "smtp.office365.com", "587", mb.email, mb.password or "",
                "outlook.office365.com", "993", mb.email, mb.password or "",
                "true",
            ])
    else:  # generic
        writer = csv.writer(output)
        writer.writerow(["email", "password", "display_name", "first_name", "last_name", "imap_host", "imap_port", "smtp_host", "smtp_port"])
        for mb in mailboxes:
            parts = mb.display_name.split(" ", 1)
            first = parts[0] if parts else mb.display_name
            last = parts[1] if len(parts) > 1 else ""
            writer.writerow([
                mb.email, mb.password or "", mb.display_name, first, last,
                "outlook.office365.com", "993",
                "smtp.office365.com", "587",
            ])

    output.seek(0)

    batch_label = ""
    if batch_id:
        batch = await db.get(SetupBatch, batch_id)
        batch_label = f"_{batch.name}" if batch else ""

    filename = f"pending_upload{batch_label}_{sequencer_format}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"

    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============================================================================
# EXPORT ALL — Full export with upload status column
# ============================================================================

@router.get("/export-all")
async def export_all_csv(
    batch_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Export ALL mailboxes with their upload status. Useful for auditing.
    """
    filters = []
    if batch_id:
        filters.append(Mailbox.batch_id == batch_id)

    query = select(Mailbox).options(selectinload(Mailbox.tenant)).order_by(Mailbox.email)
    if filters:
        query = query.where(and_(*filters))

    result = await db.execute(query)
    mailboxes = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "email", "display_name", "password", "tenant", "domain", "batch",
        "setup_complete", "uploaded_to_sequencer", "uploaded_at", "sequencer_name",
        "upload_error", "status",
    ])

    batch_cache: dict[UUID, str] = {}
    for mb in mailboxes:
        batch_name = ""
        if mb.batch_id:
            if mb.batch_id not in batch_cache:
                batch = await db.get(SetupBatch, mb.batch_id)
                batch_cache[mb.batch_id] = batch.name if batch else ""
            batch_name = batch_cache[mb.batch_id]

        tenant_name = ""
        domain_name = mb.email.split("@")[1] if "@" in mb.email else ""
        if mb.tenant:
            tenant_name = mb.tenant.name or mb.tenant.onmicrosoft_domain or ""

        writer.writerow([
            mb.email, mb.display_name, mb.password or "",
            tenant_name, domain_name, batch_name,
            mb.setup_complete, mb.uploaded_to_sequencer,
            mb.uploaded_at.isoformat() if mb.uploaded_at else "",
            mb.sequencer_name or "",
            mb.upload_error or "",
            mb.status.value,
        ])

    output.seek(0)
    filename = f"all_mailboxes_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"

    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
