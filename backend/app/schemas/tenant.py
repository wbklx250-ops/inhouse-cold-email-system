from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.tenant import TenantStatus


class TenantBase(BaseModel):
    name: str
    provider: str


class TenantCreate(TenantBase):
    model_config = ConfigDict(populate_by_name=True)
    microsoft_tenant_id: str
    admin_email: str
    admin_password: str
    onmicrosoft_domain: str
    licensed_user_upn: str | None = Field(default=None, alias="licensed_user_email")
    provider_order_id: str | None = None


class TenantUpdate(BaseModel):
    microsoft_tenant_id: str | None = None
    name: str | None = None
    onmicrosoft_domain: str | None = None
    provider: str | None = None
    admin_email: str | None = None
    admin_password: str | None = None
    status: TenantStatus | None = None
    target_mailbox_count: int | None = None
    domain_id: UUID | None = None
    # Optional fields
    licensed_user_upn: str | None = None
    provider_order_id: str | None = None
    mx_value: str | None = None
    spf_value: str | None = None
    dkim_selector1_cname: str | None = None
    dkim_selector2_cname: str | None = None
    setup_error: str | None = None


class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    microsoft_tenant_id: str
    name: str
    onmicrosoft_domain: str
    provider: str
    admin_email: str
    status: TenantStatus
    target_mailbox_count: int
    domain_id: UUID | None = None
    
    # Licensed user (using model field names)
    licensed_user_upn: str | None = None
    licensed_user_id: str | None = None
    licensed_user_created: bool = False
    
    # M365 setup tracking
    first_login_completed: bool = False
    domain_added_to_m365: bool = False
    domain_verified_in_m365: bool = False
    
    # DNS tracking
    mx_record_added: bool = False
    spf_record_added: bool = False
    mx_value: str | None = None
    spf_value: str | None = None
    
    # DKIM tracking
    dkim_selector1_cname: str | None = None
    dkim_selector2_cname: str | None = None
    dkim_cnames_added: bool = False
    dkim_enabled: bool = False
    
    # Mailbox tracking
    mailbox_count: int = 0
    mailboxes_generated: bool = False
    mailboxes_created: bool = False
    mailboxes_configured: int = 0
    
    # Custom domain
    custom_domain: str | None = None
    
    # Error tracking
    setup_step: str | None = None
    setup_error: str | None = None
    provider_order_id: str | None = None
    
    # Batch relationship
    batch_id: UUID | None = None
    
    # Timestamps
    created_at: datetime
    updated_at: datetime


class TenantList(BaseModel):
    items: list[TenantRead]
    total: int
    page: int
    per_page: int


class TenantBulkImport(BaseModel):
    """Schema for bulk importing tenants from CSV."""
    model_config = ConfigDict(populate_by_name=True)
    microsoft_tenant_id: str
    name: str
    onmicrosoft_domain: str
    provider: str
    admin_email: str
    admin_password: str
    licensed_user_upn: str | None = Field(default=None, alias="licensed_user_email")
    provider_order_id: str | None = None


class TenantBulkImportResult(BaseModel):
    """Result of bulk tenant import operation."""
    total: int
    created: int
    skipped: int
    failed: int
    results: List[Dict[str, Any]]  # [{"tenant": "name", "status": "created|skipped|failed", "reason": "..."}]