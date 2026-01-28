"""
Azure Automation Service - Triggers PowerShell runbooks for Exchange operations.

Architecture:
  Railway (FastAPI) → HTTP webhook → Azure Automation → PowerShell → Exchange Online
                                           ↓
                                     Callback to Railway with results
"""

import json
import logging
from typing import List, Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)


class AzureAutomationService:
    """Service to trigger Azure Automation runbooks for Exchange operations."""

    def __init__(self, webhook_url: str, callback_base_url: str | None = None):
        """
        Initialize Azure Automation service.

        Args:
            webhook_url: Azure Automation webhook URL (from Azure Portal)
            callback_base_url: Base URL for callbacks (e.g., https://your-app.railway.app)
        """
        self.webhook_url = webhook_url
        self.callback_base_url = callback_base_url

    async def create_shared_mailboxes(
        self,
        tenant_id: str,
        admin_email: str,
        admin_password: str,
        mailboxes: List[Dict[str, str]],
        delegate_to: str,
    ) -> Dict[str, Any]:
        """
        Trigger Azure Automation to create shared mailboxes.

        Args:
            tenant_id: Internal tenant UUID for callback routing
            admin_email: M365 admin email
            admin_password: M365 admin password
            mailboxes: List of {"email": "...", "display_name": "..."} dicts
            delegate_to: Licensed user UPN to grant FullAccess/SendAs

        Returns:
            {"status": "started", "job_id": "..."} on success
            {"status": "error", "message": "..."} on failure
        """

        logger.info(
            "[%s] Triggering Azure Automation for %s mailboxes",
            tenant_id[:8],
            len(mailboxes),
        )

        mailboxes_with_delegate = [
            {**mailbox, "delegate_to": delegate_to} for mailbox in mailboxes
        ]

        callback_url = None
        if self.callback_base_url:
            callback_url = (
                f"{self.callback_base_url}/api/v1/webhooks/azure/mailboxes/{tenant_id}"
            )

        payload = {
            "AdminEmail": admin_email,
            "AdminPassword": admin_password,
            "MailboxesJson": json.dumps(mailboxes_with_delegate),
            "CallbackUrl": callback_url,
            "TenantId": tenant_id,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(self.webhook_url, json=payload, timeout=30)

            if response.status_code == 202:
                job_id = response.headers.get("x-ms-request-id", "unknown")
                logger.info(
                    "[%s] Azure Automation job started: %s", tenant_id[:8], job_id
                )
                return {
                    "status": "started",
                    "job_id": job_id,
                    "mailbox_count": len(mailboxes),
                }

            error_msg = response.text[:500]
            logger.error(
                "[%s] Azure Automation failed: %s - %s",
                tenant_id[:8],
                response.status_code,
                error_msg,
            )
            return {"status": "error", "message": f"HTTP {response.status_code}: {error_msg}"}

        except httpx.TimeoutException:
            logger.error("[%s] Azure Automation webhook timeout", tenant_id[:8])
            return {"status": "error", "message": "Webhook request timed out"}
        except Exception as exc:
            logger.error("[%s] Azure Automation request failed: %s", tenant_id[:8], exc)
            return {"status": "error", "message": str(exc)}

    async def fix_display_names(
        self,
        tenant_id: str,
        admin_email: str,
        admin_password: str,
        mailboxes: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """
        Trigger Azure Automation to fix mailbox display names.

        Args:
            tenant_id: Internal tenant UUID
            admin_email: M365 admin email
            admin_password: M365 admin password
            mailboxes: List of {"email": "...", "display_name": "..."} dicts
        """

        logger.info(
            "[%s] Triggering display name fix for %s mailboxes",
            tenant_id[:8],
            len(mailboxes),
        )

        callback_url = None
        if self.callback_base_url:
            callback_url = (
                f"{self.callback_base_url}/api/v1/webhooks/azure/displaynames/{tenant_id}"
            )

        payload = {
            "AdminEmail": admin_email,
            "AdminPassword": admin_password,
            "MailboxesJson": json.dumps(mailboxes),
            "CallbackUrl": callback_url,
            "TenantId": tenant_id,
            "Operation": "FixDisplayNames",
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(self.webhook_url, json=payload, timeout=30)

            if response.status_code == 202:
                job_id = response.headers.get("x-ms-request-id", "unknown")
                logger.info(
                    "[%s] Display name fix job started: %s", tenant_id[:8], job_id
                )
                return {"status": "started", "job_id": job_id}

            return {"status": "error", "message": response.text[:500]}

        except Exception as exc:
            logger.error(
                "[%s] Display name fix request failed: %s", tenant_id[:8], exc
            )
            return {"status": "error", "message": str(exc)}

    async def setup_delegation(
        self,
        tenant_id: str,
        admin_email: str,
        admin_password: str,
        mailboxes: List[str],
        delegate_to: str,
    ) -> Dict[str, Any]:
        """
        Trigger Azure Automation to set up mailbox delegation.

        Args:
            tenant_id: Internal tenant UUID
            admin_email: M365 admin email
            admin_password: M365 admin password
            mailboxes: List of mailbox email addresses
            delegate_to: User to grant access to
        """

        logger.info(
            "[%s] Triggering delegation for %s mailboxes",
            tenant_id[:8],
            len(mailboxes),
        )

        callback_url = None
        if self.callback_base_url:
            callback_url = (
                f"{self.callback_base_url}/api/v1/webhooks/azure/delegation/{tenant_id}"
            )

        payload = {
            "AdminEmail": admin_email,
            "AdminPassword": admin_password,
            "MailboxesJson": json.dumps(mailboxes),
            "DelegateTo": delegate_to,
            "CallbackUrl": callback_url,
            "TenantId": tenant_id,
            "Operation": "SetupDelegation",
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(self.webhook_url, json=payload, timeout=30)

            if response.status_code == 202:
                job_id = response.headers.get("x-ms-request-id", "unknown")
                logger.info(
                    "[%s] Delegation job started: %s", tenant_id[:8], job_id
                )
                return {"status": "started", "job_id": job_id}

            return {"status": "error", "message": response.text[:500]}

        except Exception as exc:
            logger.error("[%s] Delegation request failed: %s", tenant_id[:8], exc)
            return {"status": "error", "message": str(exc)}


_azure_service: Optional[AzureAutomationService] = None


def get_azure_automation_service() -> Optional[AzureAutomationService]:
    """Get configured Azure Automation service instance."""
    global _azure_service

    if _azure_service is None:
        import os

        webhook_url = os.getenv("AZURE_AUTOMATION_WEBHOOK_URL")
        callback_base = os.getenv("RAILWAY_PUBLIC_URL") or os.getenv("CALLBACK_BASE_URL")

        if webhook_url:
            _azure_service = AzureAutomationService(webhook_url, callback_base)
            logger.info("Azure Automation service initialized")
        else:
            logger.warning(
                "AZURE_AUTOMATION_WEBHOOK_URL not set - Azure Automation disabled"
            )

    return _azure_service