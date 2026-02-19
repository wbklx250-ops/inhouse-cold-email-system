from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, List

import dns.resolver
import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class CloudflareError(Exception):
    """Custom exception for Cloudflare API errors."""

    def __init__(self, message: str, status_code: int | None = None, response_body: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class CloudflareService:
    """Async client for Cloudflare API operations."""

    BASE_URL = "https://api.cloudflare.com/client/v4"

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.cloudflare_api_key or not settings.cloudflare_email or not settings.cloudflare_account_id:
            raise CloudflareError("Cloudflare API key, email, and account ID are required")
        self._api_key = settings.cloudflare_api_key
        self._email = settings.cloudflare_email
        self._account_id = settings.cloudflare_account_id
        self._headers = {
            "X-Auth-Email": self._email,
            "X-Auth-Key": self._api_key,
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        endpoint: str,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an async request to the Cloudflare API."""
        url = f"{self.BASE_URL}{endpoint}"
        logger.debug("Cloudflare API %s %s", method, url)
        if json_data:
            logger.debug("Request body: %s", json_data)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=self._headers,
                json=json_data,
            )

        logger.debug("Response status: %s", response.status_code)
        data = response.json()
        logger.debug("Response body: %s", data)

        if not data.get("success", False):
            errors = data.get("errors", [])
            error_msg = errors[0].get("message", "Unknown error") if errors else "Unknown error"
            raise CloudflareError(
                message=f"Cloudflare API error: {error_msg}",
                status_code=response.status_code,
                response_body=data,
            )

        return data

    async def create_zone(self, domain_name: str) -> dict[str, Any]:
        """
        Create a new zone in Cloudflare.

        Returns:
            {"zone_id": str, "nameservers": list[str], "status": str}
        """
        logger.info("Creating Cloudflare zone for domain: %s", domain_name)

        data = await self._request(
            method="POST",
            endpoint="/zones",
            json_data={
                "name": domain_name,
                "account": {"id": self._account_id},
                "type": "full",
            },
        )

        result = data.get("result", {})
        zone_id = result.get("id", "")
        nameservers = result.get("name_servers", [])
        status = result.get("status", "pending")

        logger.info("Zone created: zone_id=%s, nameservers=%s, status=%s", zone_id, nameservers, status)
        
        # DEBUG: Log full result to help diagnose nameserver issues
        print(f"DEBUG create_zone: Full API result for {domain_name}: {result}")
        print(f"DEBUG create_zone: Extracted nameservers: {nameservers}")
        
        # If nameservers are empty, try to fetch them from the zone details
        if not nameservers and zone_id:
            logger.warning("Nameservers empty after zone creation, fetching from zone details...")
            nameservers = await self.get_zone_nameservers(zone_id)
            print(f"DEBUG create_zone: Fetched nameservers from zone details: {nameservers}")

        return {
            "zone_id": zone_id,
            "nameservers": nameservers,
            "status": status,
        }

    async def get_zone_nameservers(self, zone_id: str) -> list[str]:
        """
        Get nameservers for a zone by fetching zone details.
        
        This is a fallback if nameservers aren't returned during zone creation.
        
        Returns:
            List of nameserver hostnames
        """
        logger.info("Fetching nameservers for zone: %s", zone_id)
        
        try:
            data = await self._request(
                method="GET",
                endpoint=f"/zones/{zone_id}",
            )
            
            nameservers = data.get("result", {}).get("name_servers", [])
            logger.info("Zone %s nameservers: %s", zone_id, nameservers)
            return nameservers
        except CloudflareError as e:
            logger.error("Failed to fetch nameservers for zone %s: %s", zone_id, e)
            return []

    async def get_zone_status(self, zone_id: str) -> str:
        """
        Get the status of a Cloudflare zone.

        Returns:
            "pending" or "active"
        """
        logger.info("Checking zone status for: %s", zone_id)

        data = await self._request(
            method="GET",
            endpoint=f"/zones/{zone_id}",
        )

        status = data.get("result", {}).get("status", "pending")
        logger.info("Zone %s status: %s", zone_id, status)
        return status

    async def get_zone_by_id(self, zone_id: str) -> Optional[dict]:
        """
        Get zone by ID to verify it still exists in Cloudflare.
        
        This is useful to verify a zone stored in the database still exists
        in Cloudflare (it may have been manually deleted).
        
        Args:
            zone_id: Cloudflare zone ID
            
        Returns:
            {"zone_id": str, "name": str, "status": str, "nameservers": list} or None if not found
        """
        logger.info("Getting zone by ID: %s", zone_id)
        
        try:
            data = await self._request(
                method="GET",
                endpoint=f"/zones/{zone_id}",
            )
            
            result = data.get("result", {})
            zone_info = {
                "zone_id": result.get("id", ""),
                "name": result.get("name", ""),
                "status": result.get("status", ""),
                "nameservers": result.get("name_servers", [])
            }
            logger.info("Zone found: zone_id=%s, name=%s, status=%s", 
                       zone_info["zone_id"], zone_info["name"], zone_info["status"])
            return zone_info
            
        except CloudflareError as e:
            # Zone not found (404) or other error
            if e.status_code == 404 or "not found" in str(e).lower():
                logger.info("Zone %s not found in Cloudflare", zone_id)
                return None
            # Re-raise other errors
            raise
        except Exception as e:
            logger.error("Error getting zone %s: %s", zone_id, e)
            return None

    async def get_zone_by_name(self, domain: str) -> Optional[dict]:
        """
        Check if a zone already exists for this domain.
        
        Args:
            domain: Domain name to check
            
        Returns:
            {"zone_id": str, "name": str, "status": str, "nameservers": list} or None if not found
        """
        logger.info("Checking if zone exists for domain: %s", domain)
        
        data = await self._request(
            method="GET",
            endpoint=f"/zones?name={domain}",
        )
        
        results = data.get("result", [])
        if results:
            zone = results[0]
            zone_info = {
                "zone_id": zone["id"],
                "name": zone["name"],
                "status": zone["status"],
                "nameservers": zone.get("name_servers", [])
            }
            logger.info("Zone found for %s: zone_id=%s, status=%s", domain, zone_info["zone_id"], zone_info["status"])
            return zone_info
        
        logger.info("No zone found for domain: %s", domain)
        return None

    async def get_or_create_zone(self, domain: str) -> dict:
        """
        Get existing zone or create new one.
        
        This is an idempotent operation - safe to call multiple times.
        
        Args:
            domain: Domain name
            
        Returns:
            {"zone_id": str, "nameservers": list, "status": str, "already_existed": bool}
        """
        # Check if zone already exists
        existing = await self.get_zone_by_name(domain)
        
        if existing:
            logger.info("Using existing zone for %s (zone_id=%s)", domain, existing["zone_id"])
            return {
                "zone_id": existing["zone_id"],
                "nameservers": existing["nameservers"],
                "status": existing["status"],
                "already_existed": True
            }
        
        # Create new zone
        logger.info("Creating new zone for %s", domain)
        zone_data = await self.create_zone(domain)
        
        return {
            "zone_id": zone_data["zone_id"],
            "nameservers": zone_data["nameservers"],
            "status": zone_data["status"],
            "already_existed": False
        }

    async def list_dns_records(self, zone_id: str) -> List[dict]:
        """
        Get all DNS records for a zone.
        
        Args:
            zone_id: Cloudflare zone ID
            
        Returns:
            List of records with id, type, name, content, proxied, priority
        """
        logger.debug("Listing DNS records for zone: %s", zone_id)
        
        data = await self._request(
            method="GET",
            endpoint=f"/zones/{zone_id}/dns_records",
        )
        
        records = [
            {
                "id": r["id"],
                "type": r["type"],
                "name": r["name"],
                "content": r["content"],
                "proxied": r.get("proxied", False),
                "priority": r.get("priority")
            }
            for r in data.get("result", [])
        ]
        
        logger.debug("Found %d DNS records in zone %s", len(records), zone_id)
        return records

    async def record_exists(self, zone_id: str, record_type: str, name: str, domain: Optional[str] = None) -> Optional[dict]:
        """
        Check if a specific DNS record already exists.
        
        Args:
            zone_id: Cloudflare zone ID
            record_type: DNS record type (MX, TXT, CNAME, etc.)
            name: Record name (e.g., "@", "autodiscover", "selector1._domainkey")
            domain: Optional domain name for name normalization
            
        Returns:
            The record dict if found, None otherwise
        """
        records = await self.list_dns_records(zone_id)
        
        # Normalize name for comparison (Cloudflare returns full domain name)
        # "@" becomes the root domain, other names get domain appended
        for record in records:
            if record["type"] != record_type:
                continue
            
            record_name = record["name"].lower()
            
            # Handle root domain records (@ -> domain.com)
            if name == "@":
                if domain and record_name == domain.lower():
                    return record
                # If no domain provided, check if it looks like a root domain (no subdomain prefix)
                if "." in record_name and record_name.count(".") == 1:
                    return record
            else:
                # Handle subdomain records (autodiscover -> autodiscover.domain.com)
                search_name = name.lower()
                if record_name.startswith(search_name + ".") or record_name == search_name:
                    return record
        
        return None

    async def update_record(self, zone_id: str, record_id: str, updates: dict) -> None:
        """
        Update an existing DNS record.
        
        Args:
            zone_id: Cloudflare zone ID
            record_id: DNS record ID
            updates: Fields to update (e.g., {"proxied": False, "content": "..."})
        """
        logger.info("Updating DNS record %s in zone %s: %s", record_id, zone_id, updates)
        
        await self._request(
            method="PATCH",
            endpoint=f"/zones/{zone_id}/dns_records/{record_id}",
            json_data=updates,
        )
        
        logger.info("DNS record %s updated successfully", record_id)

    async def delete_dns_record(self, zone_id: str, record_id: str) -> bool:
        """
        Delete a DNS record.
        
        Args:
            zone_id: Cloudflare zone ID
            record_id: DNS record ID to delete
            
        Returns:
            True if deleted successfully
        """
        logger.info("Deleting DNS record %s from zone %s", record_id, zone_id)
        
        await self._request(
            method="DELETE",
            endpoint=f"/zones/{zone_id}/dns_records/{record_id}",
        )
        
        logger.info("DNS record %s deleted successfully", record_id)
        return True

    async def get_dns_records_by_type(self, zone_id: str, record_type: str) -> List[dict]:
        """
        Get all DNS records of a specific type for a zone.
        
        Args:
            zone_id: Cloudflare zone ID
            record_type: DNS record type (TXT, CNAME, MX, etc.)
            
        Returns:
            List of records with id, name, content, etc.
        """
        logger.debug("Getting %s records for zone: %s", record_type, zone_id)
        
        records = await self.list_dns_records(zone_id)
        filtered = [r for r in records if r["type"] == record_type]
        
        logger.debug("Found %d %s records in zone %s", len(filtered), record_type, zone_id)
        return filtered

    async def delete_conflicting_spf_records(self, zone_id: str, domain: str, keep_value: Optional[str] = None) -> int:
        """
        Delete all SPF (TXT records with v=spf1) except optionally one with specific value.
        
        M365 requires exactly ONE SPF record. If there are multiple, or one with wrong value,
        we need to delete them before adding the correct one.
        
        Args:
            zone_id: Cloudflare zone ID
            domain: Domain name (for logging and name matching)
            keep_value: Optional SPF value to keep (don't delete record with this content)
            
        Returns:
            Number of records deleted
        """
        logger.info("[%s] Checking for conflicting SPF records...", domain)
        
        records = await self.get_dns_records_by_type(zone_id, "TXT")
        deleted_count = 0
        
        for record in records:
            content = record.get("content", "")
            record_name = record.get("name", "").lower()
            
            # Check if this is an SPF record at root domain
            if "v=spf1" in content.lower():
                # Check if it's at root domain (name == domain)
                if record_name == domain.lower():
                    if keep_value and content == keep_value:
                        logger.info("[%s] Keeping correct SPF record: %s", domain, content[:50])
                        continue
                    
                    logger.info("[%s] Deleting conflicting SPF record: %s", domain, content[:50])
                    await self.delete_dns_record(zone_id, record["id"])
                    deleted_count += 1
        
        logger.info("[%s] Deleted %d conflicting SPF records", domain, deleted_count)
        return deleted_count

    async def delete_conflicting_dkim_records(self, zone_id: str, domain: str) -> int:
        """
        Delete existing DKIM CNAME records (selector1._domainkey and selector2._domainkey).
        
        DKIM CNAME values change when domain is re-added to M365, so we need to delete
        old records before adding new ones to avoid "duplicate" errors.
        
        Args:
            zone_id: Cloudflare zone ID
            domain: Domain name (for logging and name matching)
            
        Returns:
            Number of records deleted
        """
        logger.info("[%s] Checking for existing DKIM CNAME records...", domain)
        
        records = await self.get_dns_records_by_type(zone_id, "CNAME")
        deleted_count = 0
        
        for record in records:
            record_name = record.get("name", "").lower()
            
            # Check for selector1._domainkey or selector2._domainkey
            if "selector1._domainkey" in record_name or "selector2._domainkey" in record_name:
                logger.info("[%s] Deleting existing DKIM CNAME: %s -> %s", 
                           domain, record_name, record.get("content", "")[:50])
                await self.delete_dns_record(zone_id, record["id"])
                deleted_count += 1
        
        logger.info("[%s] Deleted %d existing DKIM CNAME records", domain, deleted_count)
        return deleted_count

    async def replace_spf_record(self, zone_id: str, domain: str, new_spf_value: str) -> str:
        """
        Replace all SPF records with a single correct one.
        
        1. Delete ALL existing SPF records at root domain
        2. Create the new SPF record
        
        Args:
            zone_id: Cloudflare zone ID
            domain: Domain name
            new_spf_value: The correct SPF value (e.g., "v=spf1 include:spf.protection.outlook.com -all")
            
        Returns:
            New record ID
        """
        logger.info("[%s] Replacing SPF record with: %s", domain, new_spf_value)
        
        # Delete all existing SPF records
        await self.delete_conflicting_spf_records(zone_id, domain, keep_value=None)
        
        # Create the new SPF record
        record_id = await self.create_txt_record(zone_id, "@", new_spf_value)
        logger.info("[%s] Created new SPF record: %s", domain, record_id)
        
        return record_id

    async def replace_dkim_cnames(
        self, zone_id: str, domain: str, selector1_value: str, selector2_value: str
    ) -> dict:
        """
        Replace DKIM CNAME records with correct values.
        
        1. Delete ALL existing selector1._domainkey and selector2._domainkey CNAMEs
        2. Create new ones with the correct values
        
        Args:
            zone_id: Cloudflare zone ID
            domain: Domain name
            selector1_value: CNAME target for selector1._domainkey
            selector2_value: CNAME target for selector2._domainkey
            
        Returns:
            {"selector1_id": str, "selector2_id": str}
        """
        logger.info("[%s] Replacing DKIM CNAME records", domain)
        logger.info("[%s] selector1 target: %s", domain, selector1_value)
        logger.info("[%s] selector2 target: %s", domain, selector2_value)
        
        # Delete existing DKIM CNAMEs
        await self.delete_conflicting_dkim_records(zone_id, domain)
        
        result = {"selector1_id": None, "selector2_id": None}
        
        # Create new DKIM CNAMEs (MUST be proxied=False for DKIM!)
        try:
            result["selector1_id"] = await self.create_cname_record(
                zone_id, "selector1._domainkey", selector1_value, proxied=False
            )
            logger.info("[%s] Created selector1._domainkey CNAME", domain)
        except Exception as e:
            logger.error("[%s] Failed to create selector1 CNAME: %s", domain, e)
        
        try:
            result["selector2_id"] = await self.create_cname_record(
                zone_id, "selector2._domainkey", selector2_value, proxied=False
            )
            logger.info("[%s] Created selector2._domainkey CNAME", domain)
        except Exception as e:
            logger.error("[%s] Failed to create selector2 CNAME: %s", domain, e)
        
        return result

    async def ensure_verification_txt(self, zone_id: str, domain: str, txt_value: str) -> bool:
        """
        Add or REPLACE the M365 verification TXT record.
        
        IMPORTANT: M365 generates a NEW verification code (MS=msXXXXXXXX) every time
        you add a domain. If there's an old MS= record from a previous attempt,
        it MUST be replaced with the new one, or verification will fail.
        
        This method:
        1. Gets all TXT records at @ (root domain)
        2. Finds any that start with MS=ms (M365 verification records)
        3. If found with SAME value -> done (already correct)
        4. If found with DIFFERENT value -> DELETE it first
        5. Creates the new TXT record
        
        Args:
            zone_id: Cloudflare zone ID
            domain: Domain name (for logging and name matching)
            txt_value: The new MS=msXXXXXXXX verification value from M365
            
        Returns:
            True if record is now correct
        """
        logger.info("[%s] Ensuring verification TXT: %s", domain, txt_value)
        
        # Get all DNS records for the zone
        records = await self.list_dns_records(zone_id)
        
        # Check existing TXT records at root domain
        for record in records:
            if record["type"] != "TXT":
                continue
            
            # Check if this is a root domain TXT record
            record_name = record["name"].lower()
            domain_lower = domain.lower()
            
            # Root domain TXT records have name == domain
            if record_name == domain_lower:
                content = record.get("content", "")
                
                # Check if it's an M365 verification record (starts with MS=ms)
                if content.startswith("MS=ms") or content.startswith("ms=ms"):
                    if content == txt_value:
                        logger.info("[%s] Verification TXT already correct: %s", domain, txt_value)
                        return True
                    else:
                        # Different value - DELETE the old one!
                        logger.info("[%s] REPLACING old verification TXT: %s -> %s", 
                                   domain, content, txt_value)
                        await self.delete_dns_record(zone_id, record["id"])
                        # Continue to create the new record below
        
        # Create the new verification TXT record
        logger.info("[%s] Creating verification TXT: %s", domain, txt_value)
        await self.create_txt_record(zone_id, "@", txt_value)
        return True

    async def ensure_txt_record(self, zone_id: str, name: str, content: str, domain: Optional[str] = None) -> str:
        """
        Create TXT record only if it doesn't exist with this content.
        
        This is an idempotent operation - safe to call multiple times.
        
        NOTE: TXT records can have MULTIPLE values at the same name (e.g., MS verification, SPF, DMARC all at "@").
        This function checks ALL TXT records at the name to find one with matching content,
        not just the first one found.
        
        Args:
            zone_id: Cloudflare zone ID
            name: Record name (e.g., "@" for root, "_dmarc" for DMARC)
            content: TXT record value
            domain: Optional domain name for name normalization
            
        Returns:
            record_id (existing or newly created)
        """
        # Get all DNS records and search for matching TXT record
        records = await self.list_dns_records(zone_id)
        
        # Check ALL TXT records at this name for matching content
        # (There can be multiple TXT records at "@": MS verification, SPF, DMARC, etc.)
        for record in records:
            if record["type"] != "TXT":
                continue
            
            # Check if this record is at the right name
            record_name = record["name"].lower()
            matches_name = False
            
            if name == "@":
                # Root domain - record name should be exactly the domain
                if domain and record_name == domain.lower():
                    matches_name = True
                # If no domain provided, check if it looks like a root domain
                elif "." in record_name and record_name.count(".") == 1:
                    matches_name = True
            else:
                # Subdomain - record name should start with the subdomain
                search_name = name.lower()
                if record_name.startswith(search_name + ".") or record_name == search_name:
                    matches_name = True
            
            # If name matches and content matches, we found our record!
            if matches_name and record["content"] == content:
                logger.info("TXT record already exists with correct content: %s (record_id: %s)", name, record["id"])
                return record["id"]
        
        # No exact match found - create new record
        logger.info("Creating new TXT record: %s with content: %s...", name, content[:50])
        return await self.create_txt_record(zone_id, name, content)

    async def ensure_mx_record(self, zone_id: str, name: str, target: str, priority: int, domain: Optional[str] = None) -> str:
        """
        Create MX record only if it doesn't exist.
        
        This is an idempotent operation - safe to call multiple times.
        
        Args:
            zone_id: Cloudflare zone ID
            name: Record name (e.g., "@" for root)
            target: Mail server target
            priority: MX priority
            domain: Optional domain name for name normalization
            
        Returns:
            record_id (existing or newly created)
        """
        existing = await self.record_exists(zone_id, "MX", name, domain)
        
        if existing:
            # Check if MX target matches (content contains the target)
            if target.lower() in existing["content"].lower():
                logger.info("MX record already exists with correct target: %s -> %s", name, target)
                return existing["id"]
            else:
                logger.info("MX record exists but with different target, creating new record: %s", name)
        
        # Create new record
        return await self.create_mx_record(zone_id, name, target, priority)

    async def ensure_cname_record(self, zone_id: str, name: str, target: str, proxied: bool = False, domain: Optional[str] = None) -> str:
        """
        Create CNAME record only if it doesn't exist. Updates proxied setting if different.
        
        This is an idempotent operation - safe to call multiple times.
        
        Args:
            zone_id: Cloudflare zone ID
            name: Record name (e.g., "autodiscover", "selector1._domainkey")
            target: CNAME target
            proxied: Whether to proxy through Cloudflare (default False for DKIM/mail)
            domain: Optional domain name for name normalization
            
        Returns:
            record_id (existing or newly created)
        """
        existing = await self.record_exists(zone_id, "CNAME", name, domain)
        
        if existing:
            # Check if proxied setting is correct (important for DKIM)
            if existing["proxied"] != proxied:
                logger.info("CNAME record exists but proxied setting is wrong (%s), updating to %s", 
                           existing["proxied"], proxied)
                await self.update_record(zone_id, existing["id"], {"proxied": proxied})
            else:
                logger.info("CNAME record already exists with correct settings: %s -> %s", name, target)
            return existing["id"]
        
        # Create new record
        return await self.create_cname_record(zone_id, name, target, proxied)

    async def ensure_email_dns_records(self, zone_id: str, domain: str) -> dict:
        """
        Ensure all required email DNS records exist.
        Creates only missing records.
        
        This is an idempotent operation - safe to call multiple times.
        
        Args:
            zone_id: Cloudflare zone ID
            domain: Domain name
            
        Returns:
            {
                "mx": {"success": bool, "record_id": str, "error": str?},
                "spf": {"success": bool, "record_id": str, "error": str?},
                "autodiscover": {"success": bool, "record_id": str, "error": str?}
            }
        """
        logger.info("Ensuring email DNS records exist for %s (zone: %s)", domain, zone_id)
        
        results = {
            "mx": {"success": False, "record_id": None, "error": None},
            "spf": {"success": False, "record_id": None, "error": None},
            "autodiscover": {"success": False, "record_id": None, "error": None}
        }
        
        # MX Record - points to Microsoft 365
        mx_target = f"{domain.replace('.', '-')}.mail.protection.outlook.com"
        try:
            record_id = await self.ensure_mx_record(zone_id, "@", mx_target, 0, domain)
            results["mx"]["success"] = True
            results["mx"]["record_id"] = record_id
            logger.info("MX record ensured for %s", domain)
        except Exception as e:
            results["mx"]["error"] = str(e)
            logger.error("Failed to ensure MX record for %s: %s", domain, e)
        
        # SPF Record - allows Microsoft 365 to send email
        spf_content = "v=spf1 include:spf.protection.outlook.com ~all"
        try:
            record_id = await self.ensure_txt_record(zone_id, "@", spf_content, domain)
            results["spf"]["success"] = True
            results["spf"]["record_id"] = record_id
            logger.info("SPF record ensured for %s", domain)
        except Exception as e:
            results["spf"]["error"] = str(e)
            logger.error("Failed to ensure SPF record for %s: %s", domain, e)
        
        # Autodiscover CNAME - for automatic email client configuration
        try:
            record_id = await self.ensure_cname_record(zone_id, "autodiscover", "autodiscover.outlook.com", proxied=False, domain=domain)
            results["autodiscover"]["success"] = True
            results["autodiscover"]["record_id"] = record_id
            logger.info("Autodiscover CNAME ensured for %s", domain)
        except Exception as e:
            results["autodiscover"]["error"] = str(e)
            logger.error("Failed to ensure autodiscover CNAME for %s: %s", domain, e)
        
        success_count = sum(1 for r in results.values() if r["success"])
        logger.info("Email DNS records ensured for %s: %d/3 successful", domain, success_count)
        
        return results

    async def ensure_dkim_cnames(
        self, zone_id: str, domain: str, selector1_value: str, selector2_value: str
    ) -> dict[str, Any]:
        """
        Ensure DKIM CNAME records exist. MUST NOT be proxied (DNS only).
        
        This is an idempotent operation - safe to call multiple times.
        
        Args:
            zone_id: Cloudflare zone ID
            domain: Domain name (for logging and normalization)
            selector1_value: CNAME target for selector1._domainkey
            selector2_value: CNAME target for selector2._domainkey

        Returns:
            {"selector1_id": str?, "selector2_id": str?, "errors": []}
        """
        logger.info("Ensuring DKIM CNAME records for zone %s, domain %s", zone_id, domain)

        result: dict[str, Any] = {
            "selector1_id": None,
            "selector2_id": None,
            "errors": [],
        }

        # Ensure selector1._domainkey CNAME
        try:
            record_id = await self.ensure_cname_record(
                zone_id=zone_id,
                name="selector1._domainkey",
                target=selector1_value,
                proxied=False,  # MUST be DNS only for DKIM
                domain=domain
            )
            result["selector1_id"] = record_id
            logger.info("DKIM selector1 CNAME ensured for %s", domain)
        except Exception as e:
            result["errors"].append(f"selector1 error: {e}")
            logger.warning("Failed to ensure DKIM selector1 for %s: %s", domain, e)

        # Ensure selector2._domainkey CNAME
        try:
            record_id = await self.ensure_cname_record(
                zone_id=zone_id,
                name="selector2._domainkey",
                target=selector2_value,
                proxied=False,  # MUST be DNS only for DKIM
                domain=domain
            )
            result["selector2_id"] = record_id
            logger.info("DKIM selector2 CNAME ensured for %s", domain)
        except Exception as e:
            result["errors"].append(f"selector2 error: {e}")
            logger.warning("Failed to ensure DKIM selector2 for %s: %s", domain, e)

        return result

    async def create_dns_record(
        self,
        zone_id: str,
        record_type: str,
        name: str,
        content: str,
        priority: int | None = None,
        proxied: bool = False,
    ) -> str:
        """
        Create a DNS record in a Cloudflare zone.

        Returns:
            record_id
        """
        logger.info(
            "Creating DNS record: zone=%s type=%s name=%s content=%s priority=%s proxied=%s",
            zone_id,
            record_type,
            name,
            content,
            priority,
            proxied,
        )

        json_data: dict[str, Any] = {
            "type": record_type,
            "name": name,
            "content": content,
            "proxied": proxied,
        }
        if priority is not None:
            json_data["priority"] = priority

        data = await self._request(
            method="POST",
            endpoint=f"/zones/{zone_id}/dns_records",
            json_data=json_data,
        )

        record_id = data.get("result", {}).get("id", "")
        logger.info("DNS record created: %s", record_id)
        return record_id

    async def create_mx_record(
        self, 
        zone_id: str, 
        name: str, 
        target: str, 
        priority: int = 0
    ) -> str:
        """
        Create MX record.

        Args:
            zone_id: Cloudflare zone ID
            name: Record name (e.g., "@" for root)
            target: Mail server target (e.g., "example-com.mail.protection.outlook.com")
            priority: MX priority (default 0)

        Returns:
            record_id
        """
        return await self.create_dns_record(
            zone_id=zone_id,
            record_type="MX",
            name=name,
            content=target,
            priority=priority,
            proxied=False,
        )

    async def create_txt_record(
        self,
        zone_id: str,
        name: str,
        value: str,
    ) -> str:
        """
        Create TXT record.

        Args:
            zone_id: Cloudflare zone ID
            name: Record name (e.g., "@" for root, "_dmarc" for DMARC)
            value: TXT record value

        Returns:
            record_id
        """
        return await self.create_dns_record(
            zone_id=zone_id,
            record_type="TXT",
            name=name,
            content=value,
            proxied=False,
        )

    async def create_cname_record(
        self,
        zone_id: str,
        name: str,
        target: str,
        proxied: bool = False,
    ) -> str:
        """
        Create CNAME record.

        Args:
            zone_id: Cloudflare zone ID
            name: Record name (e.g., "autodiscover", "selector1._domainkey")
            target: CNAME target
            proxied: Whether to proxy through Cloudflare (default False for DKIM/mail)

        Returns:
            record_id
        """
        return await self.create_dns_record(
            zone_id=zone_id,
            record_type="CNAME",
            name=name,
            content=target,
            proxied=proxied,
        )

    async def create_spf_record(self, zone_id: str) -> str:
        """
        Create SPF TXT record for Microsoft 365.

        Returns:
            record_id
        """
        spf_content = "v=spf1 include:spf.protection.outlook.com ~all"

        return await self.create_dns_record(
            zone_id=zone_id,
            record_type="TXT",
            name="@",
            content=spf_content,
            proxied=False,
        )

    async def create_dmarc_record(self, zone_id: str, domain: str) -> str:
        """
        Create DMARC TXT record.

        Returns:
            record_id
        """
        dmarc_content = f"v=DMARC1; p=none; rua=mailto:dmarc@{domain}"

        return await self.create_dns_record(
            zone_id=zone_id,
            record_type="TXT",
            name="_dmarc",
            content=dmarc_content,
            proxied=False,
        )

    async def create_all_dns_records(self, zone_id: str, domain: str) -> dict[str, str]:
        """
        Create all required DNS records (MX, SPF, DMARC).

        Returns:
            {"mx_record_id": str, "spf_record_id": str, "dmarc_record_id": str}
        """
        logger.info("Creating all DNS records for zone %s, domain %s", zone_id, domain)

        mx_record_id = await self.create_mx_record(zone_id, domain)
        spf_record_id = await self.create_spf_record(zone_id)
        dmarc_record_id = await self.create_dmarc_record(zone_id, domain)

        result = {
            "mx_record_id": mx_record_id,
            "spf_record_id": spf_record_id,
            "dmarc_record_id": dmarc_record_id,
        }
        logger.info("All DNS records created: %s", result)
        return result

    async def create_phase1_dns(self, zone_id: str, domain: str) -> dict[str, Any]:
        """
        Create Phase 1 DNS records IMMEDIATELY after zone creation (before NS update).
        These records will work once NS propagates.

        Creates:
        1. CNAME: name="@", content="www.{domain}", proxied=True (for redirect)
        2. TXT: name="_dmarc", content="v=DMARC1; p=none;"

        Returns:
            {"cname_created": True, "dmarc_created": True, "errors": []}
        """
        logger.info("Creating Phase 1 DNS records for zone %s, domain %s", zone_id, domain)

        result: dict[str, Any] = {
            "cname_created": False,
            "dmarc_created": False,
            "errors": [],
        }

        # Create CNAME for @ pointing to www (for redirect setup)
        try:
            await self.create_dns_record(
                zone_id=zone_id,
                record_type="CNAME",
                name="@",
                content=f"www.{domain}",
                proxied=True,
            )
            result["cname_created"] = True
            logger.info("Phase 1 CNAME created for %s", domain)
        except CloudflareError as e:
            result["errors"].append(f"CNAME error: {e}")
            logger.warning("Failed to create Phase 1 CNAME for %s: %s", domain, e)

        # Create basic DMARC record
        try:
            await self.create_dns_record(
                zone_id=zone_id,
                record_type="TXT",
                name="_dmarc",
                content="v=DMARC1; p=none;",
                proxied=False,
            )
            result["dmarc_created"] = True
            logger.info("Phase 1 DMARC created for %s", domain)
        except CloudflareError as e:
            result["errors"].append(f"DMARC error: {e}")
            logger.warning("Failed to create Phase 1 DMARC for %s: %s", domain, e)

        return result

    async def create_verification_txt(self, zone_id: str, domain: str, ms_value: str) -> bool:
        """
        Create M365 verification TXT record.

        Args:
            zone_id: Cloudflare zone ID
            domain: Domain name (for logging)
            ms_value: Microsoft verification value (e.g., "MS=ms12345678")

        Returns:
            True if created successfully, False otherwise
        """
        logger.info("Creating M365 verification TXT for zone %s: %s", zone_id, ms_value)

        try:
            await self.create_dns_record(
                zone_id=zone_id,
                record_type="TXT",
                name="@",
                content=ms_value,
                proxied=False,  # Must be DNS only
            )
            logger.info("M365 verification TXT created for %s", domain)
            return True
        except CloudflareError as e:
            logger.error("Failed to create M365 verification TXT for %s: %s", domain, e)
            return False

    async def create_dkim_cnames(
        self, zone_id: str, domain: str, selector1_value: str, selector2_value: str
    ) -> dict[str, Any]:
        """
        Create DKIM CNAME records. MUST NOT be proxied (DNS only).

        Args:
            zone_id: Cloudflare zone ID
            domain: Domain name (for logging)
            selector1_value: CNAME target for selector1._domainkey
            selector2_value: CNAME target for selector2._domainkey

        Returns:
            {"selector1_created": True, "selector2_created": True, "errors": []}
        """
        logger.info("Creating DKIM CNAME records for zone %s, domain %s", zone_id, domain)

        result: dict[str, Any] = {
            "selector1_created": False,
            "selector2_created": False,
            "errors": [],
        }

        # Create selector1._domainkey CNAME
        try:
            await self.create_dns_record(
                zone_id=zone_id,
                record_type="CNAME",
                name="selector1._domainkey",
                content=selector1_value,
                proxied=False,  # MUST be DNS only for DKIM
            )
            result["selector1_created"] = True
            logger.info("DKIM selector1 CNAME created for %s", domain)
        except CloudflareError as e:
            result["errors"].append(f"selector1 error: {e}")
            logger.warning("Failed to create DKIM selector1 for %s: %s", domain, e)

        # Create selector2._domainkey CNAME
        try:
            await self.create_dns_record(
                zone_id=zone_id,
                record_type="CNAME",
                name="selector2._domainkey",
                content=selector2_value,
                proxied=False,  # MUST be DNS only for DKIM
            )
            result["selector2_created"] = True
            logger.info("DKIM selector2 CNAME created for %s", domain)
        except CloudflareError as e:
            result["errors"].append(f"selector2 error: {e}")
            logger.warning("Failed to create DKIM selector2 for %s: %s", domain, e)

        return result

    async def check_ns_propagation(self, domain: str, expected_ns: list[str]) -> bool:
        """
        Check if nameservers have propagated using DNS lookup.

        Args:
            domain: Domain to check
            expected_ns: List of expected nameserver hostnames

        Returns:
            True if NS match, False otherwise
        """
        logger.info("Checking NS propagation for %s, expecting: %s", domain, expected_ns)

        def _resolve_sync() -> bool:
            """Synchronous DNS resolution - runs in thread to avoid blocking event loop."""
            resolver = dns.resolver.Resolver()
            resolver.timeout = 5
            resolver.lifetime = 10

            answers = resolver.resolve(domain, "NS")
            current_ns = sorted([str(rdata.target).rstrip(".").lower() for rdata in answers])
            expected = sorted([ns.lower() for ns in expected_ns])

            match = current_ns == expected
            logger.info(
                "NS propagation check for %s: current=%s, expected=%s, match=%s",
                domain,
                current_ns,
                expected,
                match,
            )
            return match

        try:
            # Run synchronous DNS resolution in a thread to avoid blocking the event loop
            return await asyncio.to_thread(_resolve_sync)
        except dns.resolver.NXDOMAIN:
            logger.warning("Domain %s not found (NXDOMAIN)", domain)
            return False
        except dns.resolver.NoAnswer:
            logger.warning("No NS records found for %s", domain)
            return False
        except dns.resolver.Timeout:
            logger.warning("DNS timeout checking NS for %s", domain)
            return False
        except Exception as e:
            logger.error("Error checking NS propagation for %s: %s", domain, e)
            return False

    async def bulk_create_zones(self, domains: list[str]) -> list[dict[str, Any]]:
        """
        Create zones for multiple domains with rate limiting.
        Cloudflare API rate limit: ~4 requests/second

        For each domain:
        1. Call create_zone() to create zone and get nameservers
        2. Call create_phase1_dns() to add CNAME and DMARC
        3. Wait 0.25 seconds before next domain (rate limiting)

        Returns:
            [
                {
                    "domain": "example.com",
                    "success": True,
                    "zone_id": "abc123",
                    "nameservers": ["anna.ns.cloudflare.com", "bob.ns.cloudflare.com"],
                    "phase1_dns": {"cname_created": True, "dmarc_created": True}
                },
                ...
            ]
        """
        logger.info("Bulk creating zones for %d domains", len(domains))
        results: list[dict[str, Any]] = []

        for i, domain in enumerate(domains):
            result: dict[str, Any] = {
                "domain": domain,
                "success": False,
                "zone_id": None,
                "nameservers": [],
                "phase1_dns": None,
                "error": None,
            }

            try:
                # Step 1: Create zone
                zone_data = await self.create_zone(domain)
                result["zone_id"] = zone_data["zone_id"]
                result["nameservers"] = zone_data["nameservers"]

                # Step 2: Create Phase 1 DNS records
                phase1_result = await self.create_phase1_dns(zone_data["zone_id"], domain)
                result["phase1_dns"] = phase1_result
                result["success"] = True

                logger.info("Successfully created zone for %s (%d/%d)", domain, i + 1, len(domains))

            except CloudflareError as e:
                result["error"] = str(e)
                logger.error("Failed to create zone for %s: %s", domain, e)

            results.append(result)

            # Rate limiting: wait 0.25 seconds between API calls (4 req/sec)
            if i < len(domains) - 1:
                await asyncio.sleep(0.25)

        success_count = sum(1 for r in results if r["success"])
        logger.info("Bulk zone creation complete: %d/%d successful", success_count, len(domains))

        return results

    async def create_redirect_rule(
        self, 
        zone_id: str, 
        domain: str, 
        redirect_url: str
    ) -> dict[str, Any]:
        """
        Create a Cloudflare Redirect Rule to redirect all traffic.
        
        When: hostname equals {domain} OR hostname equals www.{domain}
        Then: 301 redirect to {redirect_url}
        
        Uses Cloudflare Rulesets API (Redirect Rules):
        
        1. First, check if a redirect ruleset exists for the zone
           GET /zones/{zone_id}/rulesets?phase=http_request_dynamic_redirect
        
        2. If no ruleset, create one with the rule:
           POST /zones/{zone_id}/rulesets
        
        3. If ruleset exists, update it to add the new rule:
           PUT /zones/{zone_id}/rulesets/{ruleset_id}
        
        Returns: {
            "success": true,
            "ruleset_id": "...",
            "rule_id": "..."
        }
        """
        logger.info("Creating redirect rule for %s -> %s (zone: %s)", domain, redirect_url, zone_id)
        
        # Build the redirect rule
        rule_expression = f'(http.host eq "{domain}") or (http.host eq "www.{domain}")'
        new_rule = {
            "expression": rule_expression,
            "description": f"Redirect {domain} to {redirect_url}",
            "action": "redirect",
            "action_parameters": {
                "from_value": {
                    "status_code": 301,
                    "target_url": {
                        "value": redirect_url
                    },
                    "preserve_query_string": True
                }
            }
        }
        
        try:
            # Step 1: Check if redirect ruleset exists
            existing_rulesets = await self._request(
                method="GET",
                endpoint=f"/zones/{zone_id}/rulesets",
            )
            
            # Find existing redirect ruleset (phase = http_request_dynamic_redirect)
            redirect_ruleset = None
            for ruleset in existing_rulesets.get("result", []):
                if ruleset.get("phase") == "http_request_dynamic_redirect":
                    redirect_ruleset = ruleset
                    break
            
            if redirect_ruleset:
                # Step 3: Ruleset exists - fetch full details to get rules
                ruleset_id = redirect_ruleset["id"]
                
                # GET /rulesets doesn't include rules, need to fetch specific ruleset
                ruleset_details = await self._request(
                    method="GET",
                    endpoint=f"/zones/{zone_id}/rulesets/{ruleset_id}",
                )
                existing_rules = ruleset_details.get("result", {}).get("rules", [])
                
                # Check if rule for this domain already exists
                for rule in existing_rules:
                    if f'"{domain}"' in rule.get("expression", ""):
                        logger.info("Redirect rule already exists for %s", domain)
                        return {
                            "success": True,
                            "ruleset_id": ruleset_id,
                            "rule_id": rule.get("id"),
                            "already_exists": True,
                        }
                
                # Add new rule to existing rules
                updated_rules = existing_rules + [new_rule]
                
                update_response = await self._request(
                    method="PUT",
                    endpoint=f"/zones/{zone_id}/rulesets/{ruleset_id}",
                    json_data={
                        "rules": updated_rules,
                    },
                )
                
                # Find the new rule ID
                result_rules = update_response.get("result", {}).get("rules", [])
                new_rule_id = None
                for rule in result_rules:
                    if f'"{domain}"' in rule.get("expression", ""):
                        new_rule_id = rule.get("id")
                        break
                
                logger.info("Redirect rule added to existing ruleset for %s", domain)
                return {
                    "success": True,
                    "ruleset_id": ruleset_id,
                    "rule_id": new_rule_id,
                }
            else:
                # Step 2: No ruleset - create new one with the rule
                create_response = await self._request(
                    method="POST",
                    endpoint=f"/zones/{zone_id}/rulesets",
                    json_data={
                        "name": "Domain Redirects",
                        "kind": "zone",
                        "phase": "http_request_dynamic_redirect",
                        "rules": [new_rule],
                    },
                )
                
                result = create_response.get("result", {})
                ruleset_id = result.get("id")
                rules = result.get("rules", [])
                rule_id = rules[0].get("id") if rules else None
                
                logger.info("Created new redirect ruleset for %s", domain)
                return {
                    "success": True,
                    "ruleset_id": ruleset_id,
                    "rule_id": rule_id,
                }
                
        except CloudflareError as e:
            logger.error("Failed to create redirect rule for %s: %s", domain, e)
            raise

    async def bulk_create_redirect_rules(
        self, 
        domains: list[dict[str, str]]
    ) -> list[dict[str, Any]]:
        """
        Create redirect rules for multiple domains.
        
        domains: [
            {"zone_id": "abc", "domain": "example.com", "redirect_url": "https://main.com"},
            ...
        ]
        
        Rate limiting: 4 requests/second (0.25s between calls)
        
        Returns: [
            {"domain": "example.com", "success": true, "redirect_url": "https://main.com"},
            ...
        ]
        """
        logger.info("Bulk creating redirect rules for %d domains", len(domains))
        results: list[dict[str, Any]] = []
        
        for i, d in enumerate(domains):
            domain = d.get("domain", "")
            zone_id = d.get("zone_id", "")
            redirect_url = d.get("redirect_url", "")
            
            result: dict[str, Any] = {
                "domain": domain,
                "redirect_url": redirect_url,
                "success": False,
                "error": None,
            }
            
            try:
                rule_result = await self.create_redirect_rule(
                    zone_id=zone_id,
                    domain=domain,
                    redirect_url=redirect_url,
                )
                result["success"] = rule_result.get("success", False)
                result["ruleset_id"] = rule_result.get("ruleset_id")
                result["rule_id"] = rule_result.get("rule_id")
                result["already_exists"] = rule_result.get("already_exists", False)
                
                logger.info("Redirect rule created for %s (%d/%d)", domain, i + 1, len(domains))
                
            except Exception as e:
                result["error"] = str(e)
                logger.error("Failed to create redirect rule for %s: %s", domain, e)
            
            results.append(result)
            
            # Rate limiting: wait 0.25 seconds between API calls (4 req/sec)
            if i < len(domains) - 1:
                await asyncio.sleep(0.25)
        
        success_count = sum(1 for r in results if r["success"])
        logger.info("Bulk redirect rule creation complete: %d/%d successful", success_count, len(domains))
        
        return results


# Singleton instance for use throughout the application
# Note: This will raise CloudflareError if environment variables are not set
try:
    cloudflare_service = CloudflareService()
except CloudflareError:
    # Allow module to load even without credentials (for testing/development)
    cloudflare_service = None  # type: ignore
    logger.warning("CloudflareService not initialized - credentials not configured")