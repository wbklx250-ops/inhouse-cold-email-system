"""
Graph API Authentication with admin consent flow.

Uses the Email Platform app registration that requires admin consent per tenant.
"""

import json
import logging
import time
import urllib.parse
from typing import Optional

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By

logger = logging.getLogger(__name__)

CLIENT_ID = "ffc66428-dce1-47d2-82b8-b2ee8345f76e"
CLIENT_SECRET = "bpd8Q~w.mmfgYOOEPm1_KggfK8NKfa-UvsCT_aqM"
REDIRECT_URI = "https://login.microsoftonline.com/common/oauth2/nativeclient"


def get_graph_token_with_consent(driver: webdriver.Chrome, tenant_domain: str) -> Optional[str]:
    """Get Graph token, forcing consent prompt."""
    
    logger.info(f"Getting Graph token for {tenant_domain}")
    original_url = driver.current_url
    
    # Use prompt=consent to force the consent screen
    scope = "https://graph.microsoft.com/User.ReadWrite.All https://graph.microsoft.com/Directory.ReadWrite.All offline_access"
    
    auth_url = (
        f"https://login.microsoftonline.com/{tenant_domain}/oauth2/v2.0/authorize?"
        f"client_id={CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&scope={urllib.parse.quote(scope)}"
        f"&response_mode=query"
        f"&prompt=consent"  # Force consent screen
    )
    
    logger.info("Navigating to OAuth with consent prompt...")
    driver.get(auth_url)
    time.sleep(5)
    
    current_url = driver.current_url
    logger.info(f"Current URL: {current_url[:100]}")
    
    # Look for and click Accept button on consent screen
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        
        # Wait for Accept button
        accept_btn = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.ID, "idBtn_Accept"))
        )
        logger.info("Found Accept button, clicking...")
        accept_btn.click()
        time.sleep(5)
        logger.info("Clicked Accept")
        
    except Exception as e:
        logger.warning(f"No Accept button found: {e}")
        # Maybe already consented or auto-approved
    
    # Check for auth code in URL
    current_url = driver.current_url
    logger.info(f"After consent URL: {current_url[:150]}")
    
    if "code=" in current_url:
        parsed = urllib.parse.urlparse(current_url)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        
        if code:
            logger.info(f"✓ Got auth code, length: {len(code)}")
            token = _exchange_code_for_token(code, tenant_domain)
            driver.get(original_url)
            time.sleep(2)
            return token
    
    if "error" in current_url:
        parsed = urllib.parse.urlparse(current_url)
        params = urllib.parse.parse_qs(parsed.query)
        error = params.get("error", [""])[0]
        desc = params.get("error_description", [""])[0]
        logger.error(f"Auth error: {error} - {urllib.parse.unquote(desc)}")
    
    driver.get(original_url)
    time.sleep(2)
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
