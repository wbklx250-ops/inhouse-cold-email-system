from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import Boolean, Enum as SqlEnum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampUUIDMixin

if TYPE_CHECKING:
    from app.models.tenant import Tenant


class MailboxStatus(str, Enum):
    # Original statuses
    CREATED = "created"
    CONFIGURED = "configured"
    UPLOADED = "uploaded"
    WARMING = "warming"
    READY = "ready"
    SUSPENDED = "suspended"
    # New M365 provisioning statuses
    PENDING = "pending"          # Queued for creation, not yet in M365
    ENABLED = "enabled"          # Account enabled in M365
    PASSWORD_SET = "password_set"  # Password configured
    UPN_FIXED = "upn_fixed"      # UPN corrected to match email
    DELEGATED = "delegated"      # Delegation to licensed user complete
    ERROR = "error"              # Error state


class WarmupStage(str, Enum):
    NONE = "none"
    EARLY = "early"
    RAMPING = "ramping"
    MATURE = "mature"
    COMPLETE = "complete"


class Mailbox(TimestampUUIDMixin, Base):
    __tablename__ = "mailboxes"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    
    # FK to batch - mailbox belongs to a setup batch
    batch_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("setup_batches.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[MailboxStatus] = mapped_column(
        SqlEnum(
            MailboxStatus,
            name="mailbox_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    
    # M365 integration fields
    microsoft_object_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    upn: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Provisioning state tracking
    account_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    password_set: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    upn_fixed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    delegated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    photo_set: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    
    # Error tracking
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Warmup tracking
    warmup_stage: Mapped[WarmupStage] = mapped_column(
        SqlEnum(
            WarmupStage,
            name="warmup_stage",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="mailboxes")