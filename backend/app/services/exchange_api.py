"""
Exchange Admin REST API Service

Uses the access token extracted from Selenium to make direct API calls
to Exchange Admin Center. MUCH faster than UI automation for bulk operations.

Based on the Exchange Admin Center's internal API endpoints.
"""

import asyncio
import aiohttp
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class ExchangeAPIService:
    """Service for Exchange Admin Center REST API operations."""

    BASE_URL = "https://admin.exchange.microsoft.com/beta"
    OUTLOOK_BASE = "https://outlook.office365.com/adminapi/beta"

    def __init__(self, access_token: str):
        """
        Initialize with access token extracted from Selenium.

        Args:
            access_token: Bearer token from Exchange Admin session
        """
        self.access_token = access_token
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        base_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Make an async HTTP request to Exchange API."""
        url = f"{base_url or self.OUTLOOK_BASE}{endpoint}"

        async with aiohttp.ClientSession() as session:
            async with session.request(
                method=method,
                url=url,
                headers=self.headers,
                json=data,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status >= 400:
                    error_text = await response.text()
                    logger.error(f"Exchange API error {response.status}: {error_text}")
                    raise Exception(f"Exchange API error {response.status}: {error_text}")

                if response.content_type == "application/json":
                    return await response.json()
                return {"status": response.status, "text": await response.text()}

    # =========================================================================
    # MAILBOX OPERATIONS
    # =========================================================================

    async def create_shared_mailbox(
        self,
        display_name: str,
        email_address: str,
        alias: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new shared mailbox.

        Args:
            display_name: Display name (e.g., "Jack Zuvelek 1" - with number for uniqueness)
            email_address: Email address (e.g., "jack@domain.com")
            alias: Mail alias (defaults to local part of email)

        Returns:
            Created mailbox details
        """
        if alias is None:
            alias = email_address.split("@")[0]

        payload = {
            "DisplayName": display_name,
            "PrimarySmtpAddress": email_address,
            "Alias": alias,
            "Shared": True,
        }

        try:
            result = await self._request("POST", "/Mailbox", data=payload)
            logger.info(f"Created shared mailbox: {email_address}")
            return {"success": True, "mailbox": result}
        except Exception as e:
            logger.error(f"Failed to create mailbox {email_address}: {e}")
            return {"success": False, "error": str(e)}

    async def create_shared_mailboxes_bulk(
        self,
        mailboxes: List[Dict[str, str]],
        delay_between: float = 0.5,
    ) -> Dict[str, Any]:
        """
        Create multiple shared mailboxes.

        Args:
            mailboxes: List of dicts with 'display_name', 'email', 'index' keys
            delay_between: Seconds to wait between creations (rate limiting)

        Returns:
            Summary of created/failed mailboxes
        """
        results = {"created": [], "failed": [], "skipped": []}

        for mb in mailboxes:
            # Use numbered display name for uniqueness during creation
            numbered_display_name = f"{mb['display_name']} {mb['index']}"

            try:
                result = await self.create_shared_mailbox(
                    display_name=numbered_display_name,
                    email_address=mb["email"],
                )

                if result.get("success"):
                    results["created"].append(mb["email"])
                else:
                    # Check if it's "already exists" error
                    if "already exists" in str(result.get("error", "")).lower():
                        results["skipped"].append(mb["email"])
                    else:
                        results["failed"].append(
                            {"email": mb["email"], "error": result.get("error")}
                        )

            except Exception as e:
                results["failed"].append({"email": mb["email"], "error": str(e)})

            # Rate limiting
            await asyncio.sleep(delay_between)

        logger.info(
            "Bulk create complete: %s created, %s skipped, %s failed",
            len(results["created"]),
            len(results["skipped"]),
            len(results["failed"]),
        )

        return results

    async def update_mailbox_display_name(
        self,
        email_address: str,
        new_display_name: str,
    ) -> Dict[str, Any]:
        """
        Update a mailbox's display name (remove the number suffix).

        Args:
            email_address: Mailbox email address
            new_display_name: New display name without number
        """
        payload = {
            "Identity": email_address,
            "DisplayName": new_display_name,
        }

        try:
            await self._request("PATCH", f"/Mailbox('{email_address}')", data=payload)
            logger.info(f"Updated display name for {email_address}")
            return {"success": True}
        except Exception as e:
            logger.error(f"Failed to update display name for {email_address}: {e}")
            return {"success": False, "error": str(e)}

    async def fix_display_names_bulk(
        self,
        mailboxes: List[Dict[str, str]],
        target_display_name: str,
    ) -> Dict[str, Any]:
        """
        Fix display names for all mailboxes (remove number suffixes).

        Args:
            mailboxes: List of dicts with 'email' key
            target_display_name: The display name to set (e.g., "Jack Zuvelek")
        """
        results = {"fixed": [], "failed": []}

        for mb in mailboxes:
            result = await self.update_mailbox_display_name(
                email_address=mb["email"],
                new_display_name=target_display_name,
            )

            if result.get("success"):
                results["fixed"].append(mb["email"])
            else:
                results["failed"].append(
                    {"email": mb["email"], "error": result.get("error")}
                )

            await asyncio.sleep(0.2)  # Rate limiting

        logger.info(
            "Display name fix complete: %s fixed, %s failed",
            len(results["fixed"]),
            len(results["failed"]),
        )

        return results

    async def add_mailbox_permission(
        self,
        mailbox_email: str,
        trustee_email: str,
        access_rights: str = "FullAccess",
    ) -> Dict[str, Any]:
        """
        Add permission to a mailbox.

        Args:
            mailbox_email: The mailbox to grant access to
            trustee_email: The user getting access (e.g., me1@...)
            access_rights: "FullAccess", "SendAs", etc.
        """
        payload = {
            "Identity": mailbox_email,
            "User": trustee_email,
            "AccessRights": access_rights,
            "AutoMapping": True,
        }

        try:
            await self._request("POST", "/MailboxPermission", data=payload)
            logger.info(f"Added {access_rights} for {trustee_email} on {mailbox_email}")
            return {"success": True}
        except Exception as e:
            # Ignore "already exists" errors
            if "already" in str(e).lower():
                return {"success": True, "note": "Permission already exists"}
            logger.error(f"Failed to add permission: {e}")
            return {"success": False, "error": str(e)}

    async def add_send_as_permission(
        self,
        mailbox_email: str,
        trustee_email: str,
    ) -> Dict[str, Any]:
        """Add SendAs permission."""
        payload = {
            "Identity": mailbox_email,
            "Trustee": trustee_email,
            "AccessRights": "SendAs",
        }

        try:
            await self._request("POST", "/RecipientPermission", data=payload)
            logger.info(f"Added SendAs for {trustee_email} on {mailbox_email}")
            return {"success": True}
        except Exception as e:
            if "already" in str(e).lower():
                return {"success": True, "note": "Permission already exists"}
            logger.error(f"Failed to add SendAs: {e}")
            return {"success": False, "error": str(e)}

    async def delegate_mailbox_to_user(
        self,
        mailbox_email: str,
        licensed_user_upn: str,
    ) -> Dict[str, Any]:
        """
        Add full delegation (FullAccess + SendAs) to a mailbox.

        Args:
            mailbox_email: The shared mailbox
            licensed_user_upn: The me1@... user
        """
        results = {
            "full_access": await self.add_mailbox_permission(
                mailbox_email,
                licensed_user_upn,
                "FullAccess",
            ),
            "send_as": await self.add_send_as_permission(
                mailbox_email,
                licensed_user_upn,
            ),
        }

        success = all(r.get("success") for r in results.values())
        return {"success": success, "details": results}

    async def delegate_mailboxes_bulk(
        self,
        mailbox_emails: List[str],
        licensed_user_upn: str,
    ) -> Dict[str, Any]:
        """
        Delegate multiple mailboxes to licensed user.
        """
        results = {"delegated": [], "failed": []}

        for email in mailbox_emails:
            result = await self.delegate_mailbox_to_user(email, licensed_user_upn)

            if result.get("success"):
                results["delegated"].append(email)
            else:
                results["failed"].append(
                    {"email": email, "error": result.get("details")}
                )

            await asyncio.sleep(0.3)  # Rate limiting

        logger.info(
            "Delegation complete: %s delegated, %s failed",
            len(results["delegated"]),
            len(results["failed"]),
        )

        return results

    # =========================================================================
    # MAILBOX QUERIES
    # =========================================================================

    async def get_shared_mailboxes(self, domain: Optional[str] = None) -> List[Dict]:
        """Get list of shared mailboxes, optionally filtered by domain."""
        try:
            result = await self._request(
                "GET",
                "/Mailbox?$filter=RecipientTypeDetails eq 'SharedMailbox'",
            )
            mailboxes = result.get("value", [])

            if domain:
                mailboxes = [
                    m
                    for m in mailboxes
                    if domain in m.get("PrimarySmtpAddress", "")
                ]

            return mailboxes
        except Exception as e:
            logger.error(f"Failed to get shared mailboxes: {e}")
            return []

    async def mailbox_exists(self, email: str) -> bool:
        """Check if a mailbox already exists."""
        try:
            await self._request("GET", f"/Mailbox('{email}')")
            return True
        except Exception:
            return False


# ============================================================================
# CONVENIENCE FUNCTION
# ============================================================================


def create_exchange_service(access_token: str) -> ExchangeAPIService:
    """Create an Exchange API service instance."""
    return ExchangeAPIService(access_token)


# ============================================================================
# TESTING
# ============================================================================


if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("EXCHANGE API SERVICE TEST")
    print("=" * 60)
    print("\nThis test requires an Exchange access token.")
    print("Run token_extractor.py first to get the token.\n")

    # You would paste your token here for testing
    test_token = input("Paste your Exchange token (or press Enter to skip): ").strip()

    if not test_token:
        print("No token provided. Skipping test.")
        sys.exit(0)

    async def test():
        service = ExchangeAPIService(test_token)

        # Test: List shared mailboxes
        print("\n1. Listing shared mailboxes...")
        mailboxes = await service.get_shared_mailboxes()
        print(f"   Found {len(mailboxes)} shared mailboxes")

        if mailboxes:
            print(f"   First mailbox: {mailboxes[0].get('PrimarySmtpAddress', 'N/A')}")

    asyncio.run(test())