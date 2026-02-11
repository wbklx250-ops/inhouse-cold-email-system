"""
Instantly Account Model

Stores saved Instantly.ai credentials for reuse across uploads.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class InstantlyAccount(Base):
    """
    Stored Instantly.ai credentials.
    
    Users enter credentials once, then select from saved accounts.
    Password is stored in plain text (this is an internal tool, not public SaaS).
    """
    
    __tablename__ = "instantly_accounts"
    
    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    label: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # Friendly name, e.g. "Main Instantly Account"
    email: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )
    password: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # Instantly login password
    api_key: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # Optional API key
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<InstantlyAccount {self.label} ({self.email})>"
