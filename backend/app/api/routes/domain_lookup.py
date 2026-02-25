"""
Domain Lookup API Routes - Check domains against Microsoft's public endpoints.

No authentication with Microsoft is needed — these are publicly accessible
OpenID Connect discovery endpoints.

Tenant matching uses a multi-strategy cascade:
1. By microsoft_tenant_id (exact GUID match)
2. By custom_domain on tenant (tenant has this domain assigned)
3. By existing Domain→Tenant FK link in the domains table
4. By Tenant.domain_id FK pointing to this domain
5. By organization name fuzzy match
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.domain import Domain
from app.models.tenant import Tenant
from app.services.domain_lookup import DomainLookupService, DomainLookupResult

logger = logging.getLogger(__name__)

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
    match_method: Optional[str] = None  # How tenant was matched


class BulkLookupResponse(BaseModel):
    total: int
    connected: int
    not_connected: int
    errors: int
    results: list[LookupResultWithDB]


# ---------------------------------------------------------------------------
# Multi-strategy tenant matching
# ---------------------------------------------------------------------------

async def find_tenant_multi_strategy(
    db: AsyncSession,
    domain_name: str,
    ms_tenant_id: Optional[str],
    org_name: Optional[str],
    db_domain: Optional[Domain],
) -> tuple[Optional[Tenant], str]:
    """
    Try multiple strategies to find the matching tenant.
    Returns (tenant, match_method) or (None, "").

    Strategies in priority order:
    1. microsoft_tenant_id exact match
    2. Tenant.custom_domain matches domain name
    3. Existing Domain.tenant_id FK
    4. Tenant.domain_id FK points to this domain
    5. Organization name match against Tenant.name
    """

    # Strategy 1: Match by microsoft_tenant_id (GUID)
    if ms_tenant_id:
        result = await db.execute(
            select(Tenant).where(Tenant.microsoft_tenant_id == ms_tenant_id)
        )
        tenant = result.scalar_one_or_none()
        if tenant:
            return tenant, "tenant_id"

    # Strategy 2: Match by Tenant.custom_domain == domain name
    result = await db.execute(
        select(Tenant).where(Tenant.custom_domain == domain_name)
    )
    tenant = result.scalar_one_or_none()
    if tenant:
        return tenant, "custom_domain"

    # Strategy 3: Existing Domain→Tenant FK link
    if db_domain and db_domain.tenant_id:
        result = await db.execute(
            select(Tenant).where(Tenant.id == db_domain.tenant_id)
        )
        tenant = result.scalar_one_or_none()
        if tenant:
            return tenant, "domain_fk"

    # Strategy 4: Tenant.domain_id FK points to this domain
    if db_domain:
        result = await db.execute(
            select(Tenant).where(Tenant.domain_id == db_domain.id)
        )
        tenant = result.scalar_one_or_none()
        if tenant:
            return tenant, "tenant_domain_fk"

    # Strategy 5: Organization name match (case-insensitive)
    if org_name and org_name.strip():
        result = await db.execute(
            select(Tenant).where(Tenant.name.ilike(org_name.strip()))
        )
        tenant = result.scalar_one_or_none()
        if tenant:
            return tenant, "org_name"

    return None, ""


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
    Returns tenant connection status and matches against our database
    using multi-strategy tenant matching.
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

    # Match against our database using multi-strategy
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

        # Multi-strategy tenant matching
        if ms_result.is_connected or (db_domain and db_domain.tenant_id):
            db_tenant, match_method = await find_tenant_multi_strategy(
                db=db,
                domain_name=ms_result.domain,
                ms_tenant_id=ms_result.microsoft_tenant_id,
                org_name=ms_result.organization_name,
                db_domain=db_domain,
            )
            if db_tenant:
                enriched.db_tenant_id = str(db_tenant.id)
                enriched.db_tenant_name = db_tenant.name
                enriched.match_method = match_method

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
    Uses multi-strategy matching and auto-updates microsoft_tenant_id when
    a match is found by other means.
    """
    service = DomainLookupService()
    clean_domains = list(set([d.strip().lower() for d in request.domains if d.strip()]))

    if not clean_domains:
        raise HTTPException(status_code=400, detail="No valid domains provided")

    if len(clean_domains) > 500:
        raise HTTPException(status_code=400, detail="Maximum 500 domains per request")

    ms_results = await service.check_domains_bulk(clean_domains)

    updated = []
    already_linked = []
    tenant_id_updated = []
    no_tenant_match = []
    not_in_db = []
    not_connected = []

    for ms_result in ms_results:
        if not ms_result.is_connected:
            not_connected.append(ms_result.domain)
            continue

        # Find domain in our DB
        domain_query = await db.execute(
            select(Domain).where(Domain.name == ms_result.domain)
        )
        db_domain = domain_query.scalar_one_or_none()
        if not db_domain:
            not_in_db.append(ms_result.domain)
            logger.info(f"[sync] {ms_result.domain}: domain not in our DB")
            continue

        # Multi-strategy tenant matching
        db_tenant, match_method = await find_tenant_multi_strategy(
            db=db,
            domain_name=ms_result.domain,
            ms_tenant_id=ms_result.microsoft_tenant_id,
            org_name=ms_result.organization_name,
            db_domain=db_domain,
        )

        if not db_tenant:
            no_tenant_match.append({
                "domain": ms_result.domain,
                "microsoft_tenant_id": ms_result.microsoft_tenant_id,
                "organization_name": ms_result.organization_name,
            })
            logger.info(
                f"[sync] {ms_result.domain}: no tenant match found "
                f"(ms_id={ms_result.microsoft_tenant_id}, org={ms_result.organization_name})"
            )
            continue

        # Auto-update microsoft_tenant_id on the tenant if we matched by other means
        # and the stored ID differs or is missing
        if (
            ms_result.microsoft_tenant_id
            and match_method != "tenant_id"
            and db_tenant.microsoft_tenant_id != ms_result.microsoft_tenant_id
        ):
            old_ms_id = db_tenant.microsoft_tenant_id
            db_tenant.microsoft_tenant_id = ms_result.microsoft_tenant_id
            tenant_id_updated.append({
                "domain": ms_result.domain,
                "tenant_name": db_tenant.name,
                "old_microsoft_tenant_id": old_ms_id,
                "new_microsoft_tenant_id": ms_result.microsoft_tenant_id,
                "match_method": match_method,
            })
            logger.info(
                f"[sync] {ms_result.domain}: updated tenant {db_tenant.name} "
                f"microsoft_tenant_id: {old_ms_id} → {ms_result.microsoft_tenant_id} "
                f"(matched via {match_method})"
            )

        # Check if domain→tenant link needs updating
        if db_domain.tenant_id == db_tenant.id:
            already_linked.append({
                "domain": ms_result.domain,
                "tenant_id": str(db_tenant.id),
                "tenant_name": db_tenant.name,
                "match_method": match_method,
            })
            logger.info(
                f"[sync] {ms_result.domain}: already linked to {db_tenant.name} "
                f"(matched via {match_method})"
            )
            continue

        # Update the domain → tenant link
        old_tenant_id = str(db_domain.tenant_id) if db_domain.tenant_id else None
        db_domain.tenant_id = db_tenant.id
        updated.append({
            "domain": ms_result.domain,
            "tenant_id": str(db_tenant.id),
            "tenant_name": db_tenant.name,
            "microsoft_tenant_id": ms_result.microsoft_tenant_id,
            "match_method": match_method,
            "previous_tenant_id": old_tenant_id,
        })
        logger.info(
            f"[sync] {ms_result.domain}: linked to {db_tenant.name} "
            f"(matched via {match_method}), was {old_tenant_id}"
        )

    await db.commit()

    return {
        "total_checked": len(ms_results),
        "updated_links": len(updated),
        "already_linked": len(already_linked),
        "tenant_ids_updated": len(tenant_id_updated),
        "no_tenant_match": len(no_tenant_match),
        "not_in_db": len(not_in_db),
        "not_connected": len(not_connected),
        "updates": updated,
        "already_linked_details": already_linked,
        "tenant_id_updated_details": tenant_id_updated,
        "no_tenant_match_details": no_tenant_match,
    }
