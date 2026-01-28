"""
Graph API Authentication using Azure App Registration

Uses Authorization Code flow after Selenium handles MFA.
"""

import logging
import os
import time
import urllib.parse
from typing import Optional

import requests
from selenium import webdriver

logger = logging.getLogger(__name__)

# Azure App credentials
CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "ffc66428-dce1-47d2-82b8-b2ee8345f76e")
CLIENT_SECRET = os.getenv(
    "AZURE_CLIENT_SECRET",
    "bpd8Q~w.mmfgYOOEPm1_KggfK8NKfa-UvsCT_aqM",
)
REDIRECT_URI = "https://login.microsoftonline.com/common/oauth2/nativeclient"


def get_graph_token_via_auth_code(
    driver: webdriver.Chrome,
    tenant_domain: str,
) -> Optional[str]:
    """
    Get Graph token using Authorization Code flow.

    Selenium is already logged in (MFA done). We use that session to get an auth code,
    then exchange it for tokens using our app's client secret.
    """
    logger.info("Getting Graph token via Auth Code flow for %s", tenant_domain)

    scope = (
        "https://graph.microsoft.com/User.ReadWrite.All "
        "https://graph.microsoft.com/Directory.ReadWrite.All "
        "offline_access"
    )

    auth_url = (
        f"https://login.microsoftonline.com/{tenant_domain}/oauth2/v2.0/authorize?"
        f"client_id={CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&scope={urllib.parse.quote(scope)}"
        f"&response_mode=query"
        f"&prompt=none"
    )

    consent_url = (
        f"https://login.microsoftonline.com/{tenant_domain}/adminconsent?"
        f"client_id={CLIENT_ID}&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
    )

    try:
        original_url = driver.current_url
        logger.info("Original URL: %s", original_url)
        logger.info("Navigating to OAuth URL...")

        def _try_auth_code_flow() -> Optional[str]:
            driver.get(auth_url)
            time.sleep(5)

            current_url = driver.current_url
            logger.info("Redirect URL: %s", current_url)

            if "code=" in current_url:
                parsed = urllib.parse.urlparse(current_url)
                params = urllib.parse.parse_qs(parsed.query)
                auth_code = params.get("code", [None])[0]

                if auth_code:
                    logger.info("✓ Got auth code, length: %s", len(auth_code))
                    return _exchange_code_for_token(auth_code, tenant_domain)

            if "error" in current_url:
                parsed = urllib.parse.urlparse(current_url)
                params = urllib.parse.parse_qs(parsed.query)
                error = params.get("error", ["unknown"])[0]
                error_desc = params.get("error_description", ["no description"])[0]
                logger.error("OAuth error: %s", error)
                logger.error("Description: %s", urllib.parse.unquote(error_desc))
                if error in {"interaction_required", "consent_required"}:
                    return "CONSENT_REQUIRED"
            else:
                logger.error("No code in URL. Full URL: %s", current_url)

            return None

        token = _try_auth_code_flow()

        if token == "CONSENT_REQUIRED":
            logger.warning("Admin consent required. Auto-navigating to consent URL...")
            driver.get(consent_url)
            time.sleep(8)

            token = _try_auth_code_flow()

        if token and token != "CONSENT_REQUIRED":
            driver.get(original_url)
            time.sleep(2)
            return token

        driver.get(original_url)
        time.sleep(2)
        return None

    except Exception as exc:
        logger.error("Auth code flow failed: %s", exc)
        import traceback

        logger.error(traceback.format_exc())
        return None


def _exchange_code_for_token(auth_code: str, tenant_domain: str) -> Optional[str]:
    """Exchange authorization code for access token."""

    token_url = f"https://login.microsoftonline.com/{tenant_domain}/oauth2/v2.0/token"

    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URI,
        "scope": "https://graph.microsoft.com/.default",
    }

    logger.info("Exchanging auth code for token at %s", token_url)

    try:
        response = requests.post(token_url, data=payload, timeout=30)

        if response.status_code == 200:
            data = response.json()
            token = data.get("access_token")
            if token:
                logger.info("✓ SUCCESS! Graph token obtained, length: %s", len(token))
                return token
            logger.error("No access_token in response: %s", data)
            return None

        logger.error("Token exchange failed (%s): %s", response.status_code, response.text)
        return None

    except Exception as exc:
        logger.error("Token exchange error: %s", exc)
        return None