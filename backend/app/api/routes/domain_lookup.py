"""
Domain Lookup API Routes - Check domains against Microsoft's public endpoints.

No authentication with Microsoft is needed — these are publicly accessible
OpenID Connect discovery endpoints.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.domain import Domain
from app.models.tenant import Tenant
from app.services.domain_lookup import DomainLookupService

router = APIRouter(prefix="/api/v1/domain-lookup", tags=["domain-lookup"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class BulkLookupRequest(BaseModel):
    domains: list[str]  # List of domain names to check


class LookupResultWithDB(BaseModel):
    domain: str
    is_connected: bool
    microsoft_tenant_id: Optional[str] = None
    organization_name: Optional[str] = None
    namespace_type: Optional[str] = None
    error: Optional[str] = None
    # Database matching info
    found_in_db: bool = False
    db_domain_id: Optional[str] = None
    db_tenant_id: Optional[str] = None
    db_tenant_name: Optional[str] = None


class BulkLookupResponse(BaseModel):
    total: int
    connected: int
    not_connected: int
    errors: int
    results: list[LookupResultWithDB]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/check", response_model=BulkLookupResponse)
async def bulk_domain_lookup(
    request: BulkLookupRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Check a list of domains against Microsoft's public endpoints.
    Returns tenant connection status and matches against our database.
    """
    service = DomainLookupService()

    # Clean and deduplicate domains
    clean_domains = list(set([d.strip().lower() for d in request.domains if d.strip()]))

    if not clean_domains:
        raise HTTPException(status_code=400, detail="No valid domains provided")

    if len(clean_domains) > 500:
        raise HTTPException(status_code=400, detail="Maximum 500 domains per request")

    # Check against Microsoft
    ms_results = await service.check_domains_bulk(clean_domains)

    # Match against our database
    enriched_results: list[LookupResultWithDB] = []
    for ms_result in ms_results:
        enriched = LookupResultWithDB(**ms_result.model_dump())

        # Check if domain exists in our DB
        domain_query = await db.execute(
            select(Domain).where(Domain.name == ms_result.domain)
        )
        db_domain = domain_query.scalar_one_or_none()

        if db_domain:
            enriched.found_in_db = True
            enriched.db_domain_id = str(db_domain.id)

            # Check if tenant exists in our DB by microsoft_tenant_id
            if ms_result.microsoft_tenant_id:
                tenant_query = await db.execute(
                    select(Tenant).where(
                        Tenant.microsoft_tenant_id == ms_result.microsoft_tenant_id
                    )
                )
                db_tenant = tenant_query.scalar_one_or_none()
                if db_tenant:
                    enriched.db_tenant_id = str(db_tenant.id)
                    enriched.db_tenant_name = db_tenant.name

        enriched_results.append(enriched)

    connected = sum(1 for r in enriched_results if r.is_connected)
    errors = sum(1 for r in enriched_results if r.error)

    return BulkLookupResponse(
        total=len(enriched_results),
        connected=connected,
        not_connected=len(enriched_results) - connected,
        errors=errors,
        results=enriched_results,
    )


@router.post("/sync-to-db")
async def sync_lookup_to_database(
    request: BulkLookupRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Run domain lookup AND update our database with the tenant associations.
    - If domain exists in DB and is connected to a tenant, update the domain's tenant link.
    - If the tenant GUID is found in our DB, link them.
    """
    service = DomainLookupService()
    clean_domains = list(set([d.strip().lower() for d in request.domains if d.strip()]))

    if not clean_domains:
        raise HTTPException(status_code=400, detail="No valid domains provided")

    if len(clean_domains) > 500:
        raise HTTPException(status_code=400, detail="Maximum 500 domains per request")

    ms_results = await service.check_domains_bulk(clean_domains)

    updated = []
    for ms_result in ms_results:
        if not ms_result.is_connected or not ms_result.microsoft_tenant_id:
            continue

        # Find domain in our DB
        domain_query = await db.execute(
            select(Domain).where(Domain.name == ms_result.domain)
        )
        db_domain = domain_query.scalar_one_or_none()
        if not db_domain:
            continue

        # Find tenant in our DB by Microsoft tenant ID
        tenant_query = await db.execute(
            select(Tenant).where(
                Tenant.microsoft_tenant_id == ms_result.microsoft_tenant_id
            )
        )
        db_tenant = tenant_query.scalar_one_or_none()

        if db_tenant and db_domain.tenant_id != db_tenant.id:
            # Update the domain → tenant link
            db_domain.tenant_id = db_tenant.id
            updated.append(
                {
                    "domain": ms_result.domain,
                    "tenant_id": str(db_tenant.id),
                    "tenant_name": db_tenant.name,
                    "microsoft_tenant_id": ms_result.microsoft_tenant_id,
                }
            )

    await db.commit()

    return {
        "total_checked": len(ms_results),
        "updated_links": len(updated),
        "updates": updated,
    }
