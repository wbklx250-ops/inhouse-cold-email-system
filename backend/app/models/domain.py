from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampUUIDMixin

if TYPE_CHECKING:
    from app.models.batch import SetupBatch
    from app.models.tenant import Tenant


class DomainStatus(str, Enum):
    PURCHASED = "purchased"
    CF_ZONE_PENDING = "cf_zone_pending"
    CF_ZONE_ACTIVE = "cf_zone_active"
    ZONE_CREATED = "zone_created"  # after zone created + Phase 1 DNS added
    NS_UPDATING = "ns_updating"
    NS_PROPAGATING = "ns_propagating"
    NS_PROPAGATED = "ns_propagated"  # after NS verified via DNS lookup
    DNS_CONFIGURING = "dns_configuring"
    TENANT_LINKED = "tenant_linked"  # after linked to a tenant
    PENDING_M365 = "pending_m365"
    M365_VERIFIED = "m365_verified"  # after M365 domain verification
    PENDING_DKIM = "pending_dkim"
    ACTIVE = "active"
    PROBLEM = "problem"
    ERROR = "error"  # for error states
    RETIRED = "retired"


class Domain(TimestampUUIDMixin, Base):
    __tablename__ = "domains"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    tld: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[DomainStatus] = mapped_column(
        SqlEnum(
            DomainStatus,
            name="domain_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )

    cloudflare_zone_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cloudflare_nameservers: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    cloudflare_zone_status: Mapped[str] = mapped_column(String(50), nullable=False)

    nameservers_updated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    nameservers_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dns_records_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mx_configured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    spf_configured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dmarc_configured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    dkim_cnames_added: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dkim_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dkim_selector1_cname: Mapped[str | None] = mapped_column(String(255))
    dkim_selector2_cname: Mapped[str | None] = mapped_column(String(255))

    # Phase 1 tracking (before NS change)
    phase1_cname_added: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    phase1_dmarc_added: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # M365 verification tracking
    verification_txt_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verification_txt_added: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Error tracking
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Redirect URL (for cold email domains redirecting to main business website)
    redirect_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    redirect_configured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Milestone timestamps
    ns_propagated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    m365_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # FK to tenant - domain can be assigned to a tenant
    tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )

    # Relationship to tenant (via Domain.tenant_id FK)
    # Note: Tenant also has domain_id FK pointing back - this is the reverse side
    tenant: Mapped[Tenant | None] = relationship(
        "Tenant",
        uselist=False,
        foreign_keys=[tenant_id],
        overlaps="domain"
    )

    # FK to batch - domain belongs to a setup batch
    batch_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("setup_batches.id", ondelete="SET NULL"), nullable=True
    )

    # Relationship to batch
    batch: Mapped[Optional[SetupBatch]] = relationship(
        "SetupBatch",
        back_populates="domains",
    )