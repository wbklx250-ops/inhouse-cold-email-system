"""
OAuth Device Code Flow for Microsoft Graph API

1. Python initiates device code flow
2. Selenium navigates to microsoft.com/devicelogin
3. Selenium enters the user code
4. Python polls for and receives tokens
"""

import asyncio
import time
import logging
from typing import Optional
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


@dataclass
class TokenResponse:
    """OAuth token response."""
    access_token: str
    refresh_token: str
    expires_in: int
    expires_at: datetime = None
    
    def __post_init__(self):
        if self.expires_at is None:
            self.expires_at = datetime.utcnow() + timedelta(seconds=self.expires_in)


class DeviceCodeAuth:
    """OAuth device code flow with Selenium assistance."""
    
    DEVICE_CODE_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode"
    TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    DEVICE_LOGIN_URL = "https://microsoft.com/devicelogin"
    
    SCOPES = [
        "https://graph.microsoft.com/.default",
        "offline_access"
    ]
    
    def __init__(self):
        self.client_id = settings.MS_CLIENT_ID
    
    async def get_tokens(
        self,
        tenant_id: str,
        admin_email: str,
        admin_password: str,
        totp_secret: Optional[str] = None,
        headless: bool = True
    ) -> Optional[TokenResponse]:
        """
        Complete device code flow to get tokens.
        
        1. Initiate device code flow
        2. Use Selenium to enter code
        3. Poll for tokens
        """
        # Step 1: Get device code
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.DEVICE_CODE_URL.format(tenant=tenant_id),
                data={
                    "client_id": self.client_id,
                    "scope": " ".join(self.SCOPES)
                }
            )
            response.raise_for_status()
            data = response.json()
        
        device_code = data["device_code"]
        user_code = data["user_code"]
        interval = data.get("interval", 5)
        
        logger.info(f"Device code: {user_code}")
        
        # Step 2: Use Selenium to enter code
        from app.services.selenium.browser import create_driver
        import pyotp
        
        driver = create_driver(headless=headless)
        
        try:
            driver.get(self.DEVICE_LOGIN_URL)
            time.sleep(3)
            
            # Enter user code
            code_input = WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.ID, "otc"))
            )
            code_input.send_keys(user_code)
            
            # Click Next
            driver.find_element(By.ID, "idSIButton9").click()
            time.sleep(3)
            
            # Handle account picker if shown
            page = driver.page_source.lower()
            if "pick an account" in page:
                try:
                    other = driver.find_element(By.XPATH, "//*[contains(text(), 'Use another account')]")
                    other.click()
                    time.sleep(2)
                except:
                    pass
            
            # Enter email if needed
            try:
                email_input = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.NAME, "loginfmt"))
                )
                email_input.send_keys(admin_email)
                email_input.submit()
                time.sleep(2)
            except:
                pass
            
            # Enter password
            try:
                pwd_input = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.NAME, "passwd"))
                )
                pwd_input.send_keys(admin_password)
                pwd_input.submit()
                time.sleep(3)
            except:
                pass
            
            # Handle MFA if needed
            page = driver.page_source.lower()
            if totp_secret and ("verify" in page or "code" in page):
                try:
                    code = pyotp.TOTP(totp_secret).now()
                    code_input = driver.find_element(By.CSS_SELECTOR, "input[name='otc']")
                    code_input.send_keys(code)
                    driver.find_element(By.CSS_SELECTOR, "input[type='submit']").click()
                    time.sleep(3)
                except:
                    pass
            
            # Accept consent if shown
            try:
                accept = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.ID, "idSIButton9"))
                )
                accept.click()
                time.sleep(2)
            except:
                pass
            
        finally:
            driver.quit()
        
        # Step 3: Poll for tokens
        async with httpx.AsyncClient() as client:
            for _ in range(60):  # 5 minutes max
                response = await client.post(
                    self.TOKEN_URL.format(tenant=tenant_id),
                    data={
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        "client_id": self.client_id,
                        "device_code": device_code
                    }
                )
                
                data = response.json()
                
                if "error" in data:
                    if data["error"] == "authorization_pending":
                        await asyncio.sleep(interval)
                        continue
                    elif data["error"] == "slow_down":
                        await asyncio.sleep(interval * 2)
                        continue
                    else:
                        logger.error(f"Token error: {data['error']}")
                        return None
                else:
                    return TokenResponse(
                        access_token=data["access_token"],
                        refresh_token=data.get("refresh_token", ""),
                        expires_in=data["expires_in"]
                    )
        
        return None
    
    async def refresh_token(self, tenant_id: str, refresh_token: str) -> Optional[TokenResponse]:
        """Refresh an access token."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL.format(tenant=tenant_id),
                data={
                    "grant_type": "refresh_token",
                    "client_id": self.client_id,
                    "refresh_token": refresh_token,
                    "scope": " ".join(self.SCOPES)
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return TokenResponse(
                    access_token=data["access_token"],
                    refresh_token=data.get("refresh_token", refresh_token),
                    expires_in=data["expires_in"]
                )
        
        return None