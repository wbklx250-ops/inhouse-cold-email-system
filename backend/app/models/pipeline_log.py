"""Pipeline activity log for real-time progress tracking."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampUUIDMixin


class PipelineLog(TimestampUUIDMixin, Base):
    __tablename__ = "pipeline_logs"

    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("setup_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    step: Mapped[int] = mapped_column(Integer, nullable=False)  # Pipeline step number (1-10)
    step_name: Mapped[str] = mapped_column(String, nullable=False)  # "Create Cloudflare Zones", "First Login", etc.

    item_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # "domain", "tenant", "mailbox", or null for batch-level
    item_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # UUID of the domain/tenant/mailbox
    item_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # Human-readable (domain name, tenant name, email)

    status: Mapped[str] = mapped_column(String, nullable=False)  # "started", "completed", "failed", "retrying", "skipped"
    message: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # Short status message
    error_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Full error text if failed
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)  # Can this item be retried?
