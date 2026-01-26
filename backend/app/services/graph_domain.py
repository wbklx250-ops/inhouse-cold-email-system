"""
Microsoft Graph API Client for Domain Operations

Handles:
- Adding domains to M365 tenant
- Getting domain verification DNS records
- Verifying domain ownership
- Managing domain settings

Uses OAuth access tokens from the tenant record.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class GraphDomainError(Exception):
    """Custom exception for Graph API domain operations."""
    def __init__(self, message: str, status_code: int = None, response_data: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data


class GraphDomainService:
    """
    Microsoft Graph API client for domain operations.
    
    Uses the tenant's stored OAuth access token.
    """
    
    GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
    TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    
    def __init__(self):
        self.client_id = getattr(settings, 'MS_CLIENT_ID', None)
        self.client_secret = getattr(settings, 'MS_CLIENT_SECRET', None)
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        access_token: str,
        json_data: Dict = None,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """Make authenticated request to Graph API."""
        url = f"{self.GRAPH_BASE_URL}{endpoint}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        logger.debug(f"Graph API {method} {endpoint}")
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=json_data
            )
        
        logger.debug(f"Graph API response: {response.status_code}")
        
        # Handle empty response body (204 No Content, etc.)
        if response.status_code == 204 or not response.content:
            return {}
        
        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}
        
        # Check for errors
        if response.status_code >= 400:
            error_msg = data.get("error", {}).get("message", "Unknown error")
            error_code = data.get("error", {}).get("code", "")
            raise GraphDomainError(
                f"Graph API error ({error_code}): {error_msg}",
                status_code=response.status_code,
                response_data=data
            )
        
        return data
    
    async def refresh_token(
        self,
        tenant_id: str,
        refresh_token: str
    ) -> Optional[Tuple[str, str, datetime]]:
        """
        Refresh an access token using the refresh token.
        
        Returns: (new_access_token, new_refresh_token, expires_at) or None
        """
        if not self.client_id:
            logger.error("MS_CLIENT_ID not configured")
            return None
        
        url = self.TOKEN_URL.format(tenant=tenant_id)
        
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": refresh_token,
            "scope": "https://graph.microsoft.com/.default offline_access"
        }
        
        # Add client secret if configured
        if self.client_secret:
            data["client_secret"] = self.client_secret
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, data=data)
            
            if response.status_code != 200:
                logger.error(f"Token refresh failed: {response.status_code} - {response.text}")
                return None
            
            result = response.json()
            
            new_access_token = result["access_token"]
            new_refresh_token = result.get("refresh_token", refresh_token)
            expires_in = result.get("expires_in", 3600)
            expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
            
            logger.info("Token refreshed successfully")
            return new_access_token, new_refresh_token, expires_at
            
        except Exception as e:
            logger.error(f"Token refresh error: {e}")
            return None
    
    async def get_domain(
        self,
        access_token: str,
        domain_name: str
    ) -> Optional[Dict]:
        """
        Get domain details from M365 tenant.
        
        Returns domain object if exists, None if not found.
        """
        try:
            result = await self._request(
                "GET",
                f"/domains/{domain_name}",
                access_token
            )
            return result
        except GraphDomainError as e:
            if e.status_code == 404:
                return None
            raise
    
    async def add_domain(
        self,
        access_token: str,
        domain_name: str
    ) -> Dict:
        """
        Add a domain to the M365 tenant.
        
        Returns the created domain object.
        """
        logger.info(f"Adding domain to M365: {domain_name}")
        
        # Check if domain already exists
        existing = await self.get_domain(access_token, domain_name)
        if existing:
            logger.info(f"Domain {domain_name} already exists in M365")
            return existing
        
        # Add domain
        result = await self._request(
            "POST",
            "/domains",
            access_token,
            json_data={"id": domain_name}
        )
        
        logger.info(f"Domain {domain_name} added to M365")
        return result
    
    async def get_verification_dns_records(
        self,
        access_token: str,
        domain_name: str
    ) -> Optional[str]:
        """
        Get the verification TXT record value for a domain.
        
        Returns the TXT record content (e.g., "MS=ms12345678").
        """
        logger.info(f"Getting verification records for: {domain_name}")
        
        result = await self._request(
            "GET",
            f"/domains/{domain_name}/verificationDnsRecords",
            access_token
        )
        
        records = result.get("value", [])
        
        # Find the TXT record
        for record in records:
            if record.get("recordType") == "Txt":
                txt_value = record.get("text")
                logger.info(f"Found verification TXT: {txt_value}")
                return txt_value
        
        logger.warning(f"No TXT verification record found for {domain_name}")
        return None
    
    async def verify_domain(
        self,
        access_token: str,
        domain_name: str
    ) -> bool:
        """
        Verify domain ownership in M365.
        
        Returns True if verified successfully.
        """
        logger.info(f"Verifying domain: {domain_name}")
        
        # Check current status
        domain = await self.get_domain(access_token, domain_name)
        if domain and domain.get("isVerified"):
            logger.info(f"Domain {domain_name} is already verified")
            return True
        
        try:
            await self._request(
                "POST",
                f"/domains/{domain_name}/verify",
                access_token
            )
            logger.info(f"Domain {domain_name} verified successfully")
            return True
        except GraphDomainError as e:
            # Common error: DNS not propagated yet
            if "DNS record" in str(e) or "verification" in str(e).lower():
                logger.warning(f"Domain verification failed (DNS may not be propagated): {e}")
                return False
            raise
    
    async def get_service_configuration_records(
        self,
        access_token: str,
        domain_name: str
    ) -> Dict[str, Any]:
        """
        Get the service configuration DNS records (MX, CNAME, TXT).
        
        Returns dict with mx, spf, autodiscover values.
        """
        logger.info(f"Getting service configuration for: {domain_name}")
        
        result = await self._request(
            "GET",
            f"/domains/{domain_name}/serviceConfigurationRecords",
            access_token
        )
        
        records = result.get("value", [])
        
        config = {
            "mx": None,
            "spf": None,
            "autodiscover": None
        }
        
        for record in records:
            record_type = record.get("recordType")
            
            if record_type == "Mx":
                config["mx"] = {
                    "name": "@",
                    "target": record.get("mailExchange"),
                    "priority": record.get("preference", 0)
                }
            elif record_type == "Txt" and "spf" in record.get("text", "").lower():
                config["spf"] = {
                    "name": "@",
                    "value": record.get("text")
                }
            elif record_type == "CName" and "autodiscover" in record.get("label", "").lower():
                config["autodiscover"] = {
                    "name": record.get("label"),
                    "target": record.get("canonicalName")
                }
        
        return config
    
    async def add_domain_and_get_txt(
        self,
        access_token: str,
        domain_name: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Convenience method: Add domain and return verification TXT.
        
        Returns: (success, txt_value)
        """
        try:
            await self.add_domain(access_token, domain_name)
            txt_value = await self.get_verification_dns_records(access_token, domain_name)
            return txt_value is not None, txt_value
        except GraphDomainError as e:
            logger.error(f"Failed to add domain {domain_name}: {e}")
            return False, None


# Singleton instance
graph_domain_service = GraphDomainService()