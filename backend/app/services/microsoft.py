from __future__ import annotations

import logging
from typing import Any, Dict

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class MicrosoftGraphError(Exception):
    """Custom exception for Microsoft Graph API errors."""

    def __init__(self, message: str, status_code: int | None = None, response_body: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class MicrosoftGraphService:
    """
    Microsoft Graph API client for M365 tenant operations.
    Uses Resource Owner Password Credentials (ROPC) flow with admin credentials.
    """

    TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    GRAPH_BASE = "https://graph.microsoft.com/v1.0"

    def __init__(self) -> None:
        settings = get_settings()
        self._client_id = settings.azure_client_id
        if not self._client_id:
            raise MicrosoftGraphError("Azure Client ID is required. Set AZURE_CLIENT_ID in environment.")

    async def _request(
        self,
        method: str,
        url: str,
        token: str,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an async request to the Microsoft Graph API."""
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        logger.debug("Microsoft Graph API %s %s", method, url)
        if json_data:
            logger.debug("Request body: %s", json_data)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=json_data,
            )

        logger.debug("Response status: %s", response.status_code)

        # Handle empty responses (e.g., 204 No Content)
        if response.status_code == 204:
            return {}

        try:
            data = response.json()
        except Exception:
            data = {"raw_response": response.text}

        logger.debug("Response body: %s", data)

        # Check for error responses
        if response.status_code >= 400:
            error_msg = "Unknown error"
            if isinstance(data, dict) and "error" in data:
                error_info = data["error"]
                error_msg = error_info.get("message", str(error_info))
            raise MicrosoftGraphError(
                message=f"Microsoft Graph API error: {error_msg}",
                status_code=response.status_code,
                response_body=data,
            )

        return data

    async def get_token(
        self,
        tenant_id: str,
        admin_email: str,
        admin_password: str,
    ) -> str:
        """
        Get access token using ROPC (Resource Owner Password Credentials) flow.

        Args:
            tenant_id: The Microsoft tenant GUID
            admin_email: Admin user email address
            admin_password: Admin user password

        Returns:
            access_token string

        Raises:
            MicrosoftGraphError: If token acquisition fails

        Note:
            Requires Azure AD app registration with:
            - ROPC flow enabled (Allow public client flows = Yes)
            - Delegated permissions: Domain.ReadWrite.All, User.ReadWrite.All
        """
        logger.info("Getting access token for tenant: %s, user: %s", tenant_id, admin_email)

        token_url = self.TOKEN_URL.format(tenant_id=tenant_id)

        form_data = {
            "grant_type": "password",
            "client_id": self._client_id,
            "scope": "https://graph.microsoft.com/.default",
            "username": admin_email,
            "password": admin_password,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                token_url,
                data=form_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        logger.debug("Token response status: %s", response.status_code)

        try:
            data = response.json()
        except Exception:
            raise MicrosoftGraphError(
                message="Failed to parse token response",
                status_code=response.status_code,
                response_body=response.text,
            )

        if response.status_code != 200:
            error_desc = data.get("error_description", data.get("error", "Unknown error"))
            raise MicrosoftGraphError(
                message=f"Token acquisition failed: {error_desc}",
                status_code=response.status_code,
                response_body=data,
            )

        access_token = data.get("access_token")
        if not access_token:
            raise MicrosoftGraphError(
                message="No access_token in response",
                response_body=data,
            )

        logger.info("Successfully obtained access token for tenant: %s", tenant_id)
        return access_token

    async def add_domain(self, token: str, domain: str) -> Dict[str, Any]:
        """
        Add custom domain to M365 tenant.

        Args:
            token: Access token from get_token()
            domain: Domain name to add (e.g., "example.com")

        Returns:
            Domain object with verificationDnsRecords

        Raises:
            MicrosoftGraphError: If domain addition fails
        """
        logger.info("Adding domain to M365 tenant: %s", domain)

        url = f"{self.GRAPH_BASE}/domains"
        json_data = {"id": domain}

        result = await self._request(
            method="POST",
            url=url,
            token=token,
            json_data=json_data,
        )

        logger.info("Domain added successfully: %s", domain)
        return result

    async def get_domain_verification_records(self, token: str, domain: str) -> str:
        """
        Get verification TXT record value.

        Args:
            token: Access token from get_token()
            domain: Domain name to get verification records for

        Returns:
            The MS=msXXXXXXXX verification value

        Raises:
            MicrosoftGraphError: If request fails or no TXT record found
        """
        logger.info("Getting verification records for domain: %s", domain)

        url = f"{self.GRAPH_BASE}/domains/{domain}/verificationDnsRecords"

        result = await self._request(
            method="GET",
            url=url,
            token=token,
        )

        # Look for the TXT record in the response
        records = result.get("value", [])
        for record in records:
            if record.get("recordType") == "Txt":
                txt_value = record.get("text")
                if txt_value:
                    logger.info("Found verification TXT record for %s: %s", domain, txt_value)
                    return txt_value

        raise MicrosoftGraphError(
            message=f"No TXT verification record found for domain: {domain}",
            response_body=result,
        )

    async def verify_domain(self, token: str, domain: str) -> bool:
        """
        Trigger domain verification after TXT record is added.

        Args:
            token: Access token from get_token()
            domain: Domain name to verify

        Returns:
            True if verification successful

        Raises:
            MicrosoftGraphError: If verification fails
        """
        logger.info("Triggering domain verification for: %s", domain)

        url = f"{self.GRAPH_BASE}/domains/{domain}/verify"

        result = await self._request(
            method="POST",
            url=url,
            token=token,
        )

        # Check verification status
        is_verified = result.get("isVerified", False)
        logger.info("Domain verification result for %s: isVerified=%s", domain, is_verified)

        return is_verified

    async def get_domain_service_config(self, token: str, domain: str) -> Dict[str, str]:
        """
        Get MX and SPF configuration records.

        Args:
            token: Access token from get_token()
            domain: Domain name to get service configuration for

        Returns:
            {
                "mx_value": "tenant-com.mail.protection.outlook.com",
                "spf_value": "v=spf1 include:spf.protection.outlook.com -all"
            }

        Raises:
            MicrosoftGraphError: If request fails
        """
        logger.info("Getting service configuration records for domain: %s", domain)

        url = f"{self.GRAPH_BASE}/domains/{domain}/serviceConfigurationRecords"

        result = await self._request(
            method="GET",
            url=url,
            token=token,
        )

        config = {
            "mx_value": "",
            "spf_value": "",
        }

        records = result.get("value", [])
        for record in records:
            record_type = record.get("recordType")

            if record_type == "Mx":
                # MX record has mailExchange field
                config["mx_value"] = record.get("mailExchange", "")
                logger.debug("Found MX record: %s", config["mx_value"])

            elif record_type == "Txt":
                # SPF record is a TXT record
                txt_value = record.get("text", "")
                if txt_value.startswith("v=spf1"):
                    config["spf_value"] = txt_value
                    logger.debug("Found SPF record: %s", config["spf_value"])

        logger.info(
            "Service config for %s: MX=%s, SPF=%s",
            domain,
            config["mx_value"],
            config["spf_value"],
        )

        return config


# Singleton instance
microsoft_service = MicrosoftGraphService()