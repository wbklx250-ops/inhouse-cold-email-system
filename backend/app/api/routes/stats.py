"""Stats API endpoints for dashboard."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.domain import Domain, DomainStatus
from app.models.tenant import Tenant, TenantStatus
from app.models.mailbox import Mailbox, MailboxStatus

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])


@router.get("")
async def get_stats(db: AsyncSession = Depends(get_db)) -> dict:
    """
    Get aggregated stats for the dashboard.
    
    Returns counts for domains, tenants, and mailboxes at various stages.
    """
    # Domain counts
    domains_total_result = await db.execute(select(func.count(Domain.id)))
    domains_total = domains_total_result.scalar() or 0
    
    # Zones created = status is at or past ZONE_CREATED
    zones_created_statuses = [
        DomainStatus.ZONE_CREATED,
        DomainStatus.NS_UPDATING,
        DomainStatus.NS_PROPAGATING,
        DomainStatus.NS_PROPAGATED,
        DomainStatus.DNS_CONFIGURING,
        DomainStatus.TENANT_LINKED,
        DomainStatus.PENDING_M365,
        DomainStatus.M365_VERIFIED,
        DomainStatus.PENDING_DKIM,
        DomainStatus.ACTIVE,
    ]
    zones_created_result = await db.execute(
        select(func.count(Domain.id)).where(Domain.status.in_(zones_created_statuses))
    )
    zones_created = zones_created_result.scalar() or 0
    
    # NS propagated = status is at or past NS_PROPAGATED
    ns_propagated_statuses = [
        DomainStatus.NS_PROPAGATED,
        DomainStatus.DNS_CONFIGURING,
        DomainStatus.TENANT_LINKED,
        DomainStatus.PENDING_M365,
        DomainStatus.M365_VERIFIED,
        DomainStatus.PENDING_DKIM,
        DomainStatus.ACTIVE,
    ]
    ns_propagated_result = await db.execute(
        select(func.count(Domain.id)).where(Domain.status.in_(ns_propagated_statuses))
    )
    ns_propagated = ns_propagated_result.scalar() or 0
    
    # Redirects configured
    redirects_configured_result = await db.execute(
        select(func.count(Domain.id)).where(Domain.redirect_configured == True)
    )
    redirects_configured = redirects_configured_result.scalar() or 0
    
    # Tenant counts
    tenants_total_result = await db.execute(select(func.count(Tenant.id)))
    tenants_total = tenants_total_result.scalar() or 0
    
    # Domain verified = status is at or past DOMAIN_VERIFIED
    domain_verified_statuses = [
        TenantStatus.DOMAIN_VERIFIED,
        TenantStatus.DNS_CONFIGURING,
        TenantStatus.DKIM_CONFIGURING,
        TenantStatus.DKIM_ENABLED,
        TenantStatus.MAILBOXES_CREATING,
        TenantStatus.MAILBOXES_CONFIGURING,
        TenantStatus.CONFIGURING,
        TenantStatus.ACTIVE,
    ]
    tenants_domain_verified_result = await db.execute(
        select(func.count(Tenant.id)).where(Tenant.status.in_(domain_verified_statuses))
    )
    tenants_domain_verified = tenants_domain_verified_result.scalar() or 0
    
    # DKIM enabled
    dkim_enabled_statuses = [
        TenantStatus.DKIM_ENABLED,
        TenantStatus.MAILBOXES_CREATING,
        TenantStatus.MAILBOXES_CONFIGURING,
        TenantStatus.CONFIGURING,
        TenantStatus.ACTIVE,
    ]
    tenants_dkim_enabled_result = await db.execute(
        select(func.count(Tenant.id)).where(Tenant.status.in_(dkim_enabled_statuses))
    )
    tenants_dkim_enabled = tenants_dkim_enabled_result.scalar() or 0
    
    # Mailbox counts
    mailboxes_total_result = await db.execute(select(func.count(Mailbox.id)))
    mailboxes_total = mailboxes_total_result.scalar() or 0
    
    # Ready mailboxes
    ready_statuses = [
        MailboxStatus.READY,
        MailboxStatus.WARMING,
        MailboxStatus.CONFIGURED,
    ]
    mailboxes_ready_result = await db.execute(
        select(func.count(Mailbox.id)).where(Mailbox.status.in_(ready_statuses))
    )
    mailboxes_ready = mailboxes_ready_result.scalar() or 0
    
    return {
        "domains_total": domains_total,
        "zones_created": zones_created,
        "ns_propagated": ns_propagated,
        "redirects_configured": redirects_configured,
        "tenants_total": tenants_total,
        "tenants_m365_verified": tenants_domain_verified,
        "tenants_dkim_enabled": tenants_dkim_enabled,
        "mailboxes_total": mailboxes_total,
        "mailboxes_ready": mailboxes_ready,
    }