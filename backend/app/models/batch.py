"""Setup Batch Model - Groups domains/tenants/mailboxes into independent setup sessions."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampUUIDMixin

if TYPE_CHECKING:
    from app.models.domain import Domain
    from app.models.tenant import Tenant


class BatchStatus(str, Enum):
    """Status of a setup batch."""
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class SetupBatch(TimestampUUIDMixin, Base):
    """
    SetupBatch groups domains/tenants/mailboxes into independent setup sessions.
    
    This allows:
    - Running multiple setups in parallel
    - Pausing one batch while waiting for NS propagation
    - Starting a new batch while an old one is in progress
    - Coming back to continue a batch later
    """
    __tablename__ = "setup_batches"

    # Batch identification
    name: Mapped[str] = mapped_column(String(255), nullable=False)  # "January 2026 Setup", "Client ABC Domains"
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Progress tracking
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # 1-7
    status: Mapped[BatchStatus] = mapped_column(
        SqlEnum(
            BatchStatus,
            name="batch_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=BatchStatus.ACTIVE,
    )
    
    # Batch-wide default settings
    redirect_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # Default redirect for all domains in batch
    persona_first_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # Default persona for mailboxes
    persona_last_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    mailboxes_per_tenant: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    sequencer_app_key: Mapped[str] = mapped_column(String(50), nullable=False, default="instantly")
    
    # Completion tracking
    completed_steps: Mapped[Optional[List[int]]] = mapped_column(JSONB, nullable=True, default=list)  # e.g., [1, 2, 3]
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Upload to sequencer tracking (Feature 3)
    uploaded_to_sequencer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    uploaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Auto-progression mode (Feature 2)
    auto_progress_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_run_state: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)  # Persisted auto-run job state
    
    # Step 6 batch-level tracking
    step6_emails_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    step6_emails_generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    # NOTE: Using save-update/merge instead of delete-orphan to prevent
    # accidental mass deletion of domains/tenants/mailboxes when a batch is deleted.
    # Deleting a batch will unlink records (set batch_id=NULL) rather than delete them.
    domains: Mapped[list[Domain]] = relationship(
        "Domain",
        back_populates="batch",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    tenants: Mapped[list[Tenant]] = relationship(
        "Tenant",
        back_populates="batch",
        cascade="save-update, merge",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<SetupBatch {self.name} - Step {self.current_step} ({self.status.value})>"
