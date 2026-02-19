"""
Graph API Authentication with admin consent flow.

Uses the Email Platform app registration that requires admin consent per tenant.
Includes resilient token extraction fallbacks (storage/network/consent).
"""

import json
import logging
import time
import urllib.parse
from typing import Optional, Iterable

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By

logger = logging.getLogger(__name__)

CLIENT_ID = "ffc66428-dce1-47d2-82b8-b2ee8345f76e"
CLIENT_SECRET = "bpd8Q~w.mmfgYOOEPm1_KggfK8NKfa-UvsCT_aqM"
REDIRECT_URI = "https://login.microsoftonline.com/common/oauth2/nativeclient"


def get_graph_token_with_consent(driver: webdriver.Chrome, tenant_domain: str) -> Optional[str]:
    """Get Graph token via OAuth consent flow with resilient URL checks."""

    logger.info("Getting Graph token for %s", tenant_domain)
    original_url = driver.current_url

    scope = "https://graph.microsoft.com/User.ReadWrite.All https://graph.microsoft.com/Directory.ReadWrite.All offline_access"

    auth_url = (
        f"https://login.microsoftonline.com/{tenant_domain}/oauth2/v2.0/authorize?"
        f"client_id={CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&scope={urllib.parse.quote(scope)}"
        f"&response_mode=query"
        f"&prompt=consent"
    )

    logger.info("Navigating to OAuth consent URL...")
    driver.get(auth_url)
    time.sleep(5)

    try:
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        accept_selectors = [
            (By.ID, "idBtn_Accept"),
            (By.ID, "idSIButton9"),
            (By.XPATH, "//button[contains(., 'Accept')]") ,
            (By.XPATH, "//button[contains(., 'Allow')]") ,
        ]

        for by, value in accept_selectors:
            try:
                accept_btn = WebDriverWait(driver, 6).until(
                    EC.element_to_be_clickable((by, value))
                )
                logger.info("Found consent button, clicking...")
                accept_btn.click()
                time.sleep(4)
                break
            except Exception:
                continue
    except Exception as exc:
        logger.warning("Consent button handling error: %s", exc)

    # Wait for redirect to include code or error
    for _ in range(20):
        current_url = driver.current_url
        if "code=" in current_url or "error=" in current_url:
            break
        time.sleep(1)

    current_url = driver.current_url
    logger.info("After consent URL: %s", current_url[:180])

    if "code=" in current_url:
        parsed = urllib.parse.urlparse(current_url)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        if code:
            logger.info("✓ Got auth code, length: %s", len(code))
            token = _exchange_code_for_token(code, tenant_domain)
            driver.get(original_url)
            time.sleep(2)
            return token

    if "error" in current_url:
        parsed = urllib.parse.urlparse(current_url)
        params = urllib.parse.parse_qs(parsed.query)
        error = params.get("error", [""])[0]
        desc = params.get("error_description", [""])[0]
        logger.error("Auth error: %s - %s", error, urllib.parse.unquote(desc))

    driver.get(original_url)
    time.sleep(2)
    return None


def validate_graph_token(token: str) -> bool:
    """Validate token against Graph API."""
    try:
        response = requests.get(
            "https://graph.microsoft.com/v1.0/users?$top=1",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        return response.status_code == 200
    except Exception as exc:
        logger.debug("Token validation failed: %s", exc)
        return False


def extract_graph_token_from_storage(driver: webdriver.Chrome) -> Optional[str]:
    """Extract Graph token from browser storage after admin login."""
    logger.info("Extracting Graph token from storage...")
    driver.get("https://admin.microsoft.com/#/users")
    time.sleep(8)

    script = """
        let tokens = [];
        const storages = [localStorage, sessionStorage];
        for (const storage of storages) {
            for (let i = 0; i < storage.length; i++) {
                const key = storage.key(i);
                const value = storage.getItem(key);
                if (!value) continue;
                try {
                    const parsed = JSON.parse(value);
                    const token = parsed.secret || parsed.accessToken || parsed.access_token;
                    if (token && token.startsWith('eyJ') && token.length > 500) {
                        tokens.push(token);
                    }
                } catch(e) {
                    if (value.startsWith('eyJ') && value.length > 500) {
                        tokens.push(value);
                    }
                }
            }
        }
        return tokens;
    """

    tokens = driver.execute_script(script) or []
    logger.info("Found %s tokens in storage", len(tokens))
    for token in tokens:
        if validate_graph_token(token):
            logger.info("✓ Storage token validated")
            return token
    return None


def extract_graph_token_from_network(driver: webdriver.Chrome) -> Optional[str]:
    """Extract Graph token from Chrome performance logs."""
    logger.info("Extracting Graph token from network logs...")
    try:
        driver.get("https://admin.microsoft.com/#/users")
        time.sleep(8)
        logs = driver.get_log("performance")
        for entry in logs:
            message = json.loads(entry.get("message", "{}")).get("message", {})
            if message.get("method") != "Network.requestWillBeSent":
                continue
            params = message.get("params", {})
            request = params.get("request", {})
            headers = request.get("headers", {})
            auth_header = headers.get("Authorization") or headers.get("authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split("Bearer ")[-1].strip()
                if token and token.startswith("eyJ"):
                    if validate_graph_token(token):
                        logger.info("✓ Network token validated")
                        return token
    except Exception as exc:
        logger.warning("Network token extraction failed: %s", exc)
    return None


def get_graph_token_resilient(driver: webdriver.Chrome, tenant_domain: str) -> Optional[str]:
    """Get Graph token using storage/network extraction with consent fallback."""
    token = extract_graph_token_from_storage(driver)
    if token:
        return token
    token = extract_graph_token_from_network(driver)
    if token:
        return token
    token = get_graph_token_with_consent(driver, tenant_domain)
    if token and validate_graph_token(token):
        return token
    logger.error("Failed to obtain a valid Graph token for %s", tenant_domain)
    return None


def _exchange_code_for_token(code: str, tenant_domain: str) -> Optional[str]:
    """Exchange auth code for access token."""

    token_url = f"https://login.microsoftonline.com/{tenant_domain}/oauth2/v2.0/token"

    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "scope": "https://graph.microsoft.com/.default",
    }

    try:
        response = requests.post(token_url, data=payload, timeout=30)

        if response.status_code == 200:
            data = response.json()
            token = data.get("access_token")
            if token:
                logger.info("✓ SUCCESS! Graph token obtained, length: %s", len(token))
                return token

        logger.error("Token exchange failed: %s", response.text)
        return None

    except Exception as exc:
        logger.error("Token exchange error: %s", exc)
        return None


def extract_exchange_token(driver: webdriver.Chrome) -> Optional[str]:
    """Extract token and verify it works with Exchange API."""
    
    logger.info("Extracting Exchange token...")
    
    # Navigate to Exchange Admin to populate tokens
    driver.get("https://admin.exchange.microsoft.com/#/mailboxes")
    time.sleep(8)
    
    # Get ALL tokens from storage
    script = '''
        let tokens = [];
        const storages = [localStorage, sessionStorage];
        
        for (const storage of storages) {
            for (let i = 0; i < storage.length; i++) {
                const key = storage.key(i);
                const value = storage.getItem(key);
                if (!value) continue;
                
                try {
                    const parsed = JSON.parse(value);
                    const token = parsed.secret || parsed.accessToken || parsed.access_token;
                    if (token && token.startsWith('eyJ') && token.length > 500) {
                        tokens.push(token);
                    }
                } catch(e) {
                    // Try as raw token
                    if (value.startsWith('eyJ') && value.length > 500) {
                        tokens.push(value);
                    }
                }
            }
        }
        
        return tokens;
    '''
    
    tokens = driver.execute_script(script) or []
    logger.info(f"Found {len(tokens)} potential tokens")
    
    # Try each token against Exchange API
    for i, token in enumerate(tokens):
        try:
            # Test with a simple Exchange API call
            response = requests.get(
                "https://outlook.office365.com/adminapi/beta/Mailbox?$top=1",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"✓ Token {i+1} works with Exchange API!")
                return token
            elif response.status_code == 401:
                logger.debug(f"Token {i+1}: 401 Unauthorized")
            else:
                logger.debug(f"Token {i+1}: {response.status_code}")
                
        except Exception as e:
            logger.debug(f"Token {i+1} test failed: {e}")
    
    logger.error("No working Exchange token found")
    return None
