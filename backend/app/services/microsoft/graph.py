"""
Microsoft Graph API Client

Operations:
- Add domain to tenant
- Get verification DNS records
- Verify domain ownership
- Create users
- Assign licenses
- List available licenses
"""

import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

GRAPH_URL = "https://graph.microsoft.com/v1.0"


@dataclass
class DomainInfo:
    id: str
    is_verified: bool


@dataclass 
class DnsRecord:
    record_type: str
    label: str
    text: Optional[str] = None
    ttl: int = 3600


class GraphClient:
    """Microsoft Graph API client."""
    
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
    
    async def _request(self, method: str, endpoint: str, json: dict = None) -> dict:
        """Make authenticated request."""
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=method,
                url=f"{GRAPH_URL}{endpoint}",
                headers=self.headers,
                json=json,
                timeout=60
            )
            
            if response.status_code == 204:
                return {}
            
            if response.status_code >= 400:
                logger.error(f"Graph API error: {response.status_code} - {response.text}")
                response.raise_for_status()
            
            return response.json()
    
    # === DOMAIN OPERATIONS ===
    
    async def list_domains(self) -> List[DomainInfo]:
        """List all domains in tenant."""
        data = await self._request("GET", "/domains")
        return [
            DomainInfo(id=d["id"], is_verified=d.get("isVerified", False))
            for d in data.get("value", [])
        ]
    
    async def add_domain(self, domain: str) -> DomainInfo:
        """Add a domain to the tenant."""
        data = await self._request("POST", "/domains", json={"id": domain})
        return DomainInfo(
            id=data["id"],
            is_verified=data.get("isVerified", False)
        )
    
    async def get_domain(self, domain: str) -> Optional[DomainInfo]:
        """Get domain details."""
        try:
            data = await self._request("GET", f"/domains/{domain}")
            return DomainInfo(
                id=data["id"],
                is_verified=data.get("isVerified", False)
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise
    
    async def get_verification_records(self, domain: str) -> List[DnsRecord]:
        """Get DNS verification records for domain."""
        data = await self._request("GET", f"/domains/{domain}/verificationDnsRecords")
        
        records = []
        for r in data.get("value", []):
            if r.get("recordType") == "Txt":
                records.append(DnsRecord(
                    record_type="TXT",
                    label=r.get("label", "@"),
                    text=r.get("text", ""),
                    ttl=r.get("ttl", 3600)
                ))
        
        return records
    
    async def verify_domain(self, domain: str) -> bool:
        """Verify domain ownership."""
        try:
            await self._request("POST", f"/domains/{domain}/verify")
            return True
        except:
            return False
    
    # === USER OPERATIONS ===
    
    async def create_user(
        self,
        display_name: str,
        user_principal_name: str,
        password: str,
        mail_nickname: str = None
    ) -> dict:
        """Create a new user."""
        if not mail_nickname:
            mail_nickname = user_principal_name.split("@")[0]
        
        return await self._request("POST", "/users", json={
            "displayName": display_name,
            "userPrincipalName": user_principal_name,
            "mailNickname": mail_nickname,
            "accountEnabled": True,
            "usageLocation": "US",
            "passwordProfile": {
                "password": password,
                "forceChangePasswordNextSignIn": False
            }
        })
    
    async def update_user(self, user_id: str, updates: dict) -> None:
        """Update user properties."""
        await self._request("PATCH", f"/users/{user_id}", json=updates)
    
    async def list_licenses(self) -> List[dict]:
        """List available licenses in tenant."""
        data = await self._request("GET", "/subscribedSkus")
        return [
            {
                "sku_id": sku["skuId"],
                "sku_name": sku["skuPartNumber"],
                "available": sku.get("prepaidUnits", {}).get("enabled", 0) - sku.get("consumedUnits", 0)
            }
            for sku in data.get("value", [])
        ]
    
    async def assign_license(self, user_id: str, sku_id: str) -> None:
        """Assign a license to a user."""
        await self._request("POST", f"/users/{user_id}/assignLicense", json={
            "addLicenses": [{"skuId": sku_id}],
            "removeLicenses": []
        })