from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.mailbox import MailboxStatus, WarmupStage


class MailboxBase(BaseModel):
    email: str
    display_name: str


class MailboxCreate(MailboxBase):
    password: str
    tenant_id: UUID


class MailboxUpdate(BaseModel):
    email: str | None = None
    display_name: str | None = None
    password: str | None = None
    status: MailboxStatus | None = None
    account_enabled: bool | None = None
    password_set: bool | None = None
    upn_fixed: bool | None = None
    delegated: bool | None = None
    warmup_stage: WarmupStage | None = None


class MailboxRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str
    tenant_id: UUID
    batch_id: UUID | None = None
    status: MailboxStatus
    account_enabled: bool
    password_set: bool
    upn_fixed: bool
    delegated: bool
    setup_complete: bool = False
    warmup_stage: WarmupStage
    # Upload tracking
    uploaded_to_sequencer: bool = False
    uploaded_at: datetime | None = None
    sequencer_name: str | None = None
    upload_error: str | None = None
    created_at: datetime
    updated_at: datetime


class MailboxList(BaseModel):
    items: list[MailboxRead]
    total: int
    page: int
    per_page: int


class MailboxCredentials(BaseModel):
    email: str
    password: str


class MailboxBulkGenerate(BaseModel):
    tenant_id: UUID
    count: int = 50