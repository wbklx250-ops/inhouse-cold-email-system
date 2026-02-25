"""
Domain Lookup Service - Check domains against Microsoft's public OpenID Connect endpoints.

No authentication with Microsoft is needed — these are publicly accessible endpoints.
"""

import asyncio
import re
import logging
from typing import Optional

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class DomainLookupResult(BaseModel):
    domain: str
    is_connected: bool
    microsoft_tenant_id: Optional[str] = None
    organization_name: Optional[str] = None
    namespace_type: Optional[str] = None  # "Managed" or "Federated"
    error: Optional[str] = None


class DomainLookupService:
    """Check domains against Microsoft's public OpenID Connect endpoints."""

    OPENID_URL = "https://login.microsoftonline.com/{domain}/v2.0/.well-known/openid-configuration"
    USER_REALM_URL = "https://login.microsoftonline.com/getuserrealm.srf?login=test@{domain}"

    # Regex to extract tenant GUID from Microsoft endpoint URLs
    TENANT_ID_REGEX = re.compile(
        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        re.IGNORECASE,
    )

    async def check_domain(self, domain: str) -> DomainLookupResult:
        """Check a single domain against Microsoft endpoints."""
        result = DomainLookupResult(domain=domain.strip().lower(), is_connected=False)

        async with httpx.AsyncClient(timeout=15.0) as client:
            # Step 1: OpenID Configuration - get tenant ID
            try:
                resp = await client.get(self.OPENID_URL.format(domain=result.domain))
                if resp.status_code == 200:
                    data = resp.json()
                    token_endpoint = data.get("token_endpoint", "")
                    match = self.TENANT_ID_REGEX.search(token_endpoint)
                    if match:
                        result.is_connected = True
                        result.microsoft_tenant_id = match.group(1)
            except Exception as e:
                result.error = f"OpenID check failed: {str(e)}"

            # Step 2: User Realm - get organization name
            try:
                resp = await client.get(self.USER_REALM_URL.format(domain=result.domain))
                if resp.status_code == 200:
                    data = resp.json()
                    result.organization_name = data.get("FederationBrandName")
                    result.namespace_type = data.get("NameSpaceType")
                    # If OpenID failed but realm shows managed/federated, still connected
                    if result.namespace_type in ("Managed", "Federated") and not result.is_connected:
                        result.is_connected = True
            except Exception:
                pass  # Non-critical, we already have tenant ID from OpenID

        return result

    async def check_domains_bulk(
        self, domains: list[str], max_concurrent: int = 10
    ) -> list[DomainLookupResult]:
        """Check multiple domains with controlled concurrency."""
        semaphore = asyncio.Semaphore(max_concurrent)

        async def check_with_semaphore(domain: str) -> DomainLookupResult:
            async with semaphore:
                return await self.check_domain(domain)

        clean_domains = [d for d in domains if d.strip()]
        tasks = [check_with_semaphore(d) for d in clean_domains]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle any exceptions from gather
        final_results = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                final_results.append(
                    DomainLookupResult(
                        domain=clean_domains[i],
                        is_connected=False,
                        error=str(r),
                    )
                )
            else:
                final_results.append(r)

        return final_results
