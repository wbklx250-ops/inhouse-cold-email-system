"""
Graph API authentication using device code flow with Selenium MFA handling.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List, Dict, Any

try:
    import msal
except ModuleNotFoundError:  # pragma: no cover - environment guard
    msal = None
import httpx
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logger = logging.getLogger(__name__)


class GraphDeviceCodeAuth:
    """Get Graph API token using device code + Selenium MFA."""

    # Microsoft Graph PowerShell public client ID
    CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"

    def __init__(
        self,
        driver: webdriver.Chrome,
        tenant_domain: str,
        admin_email: str,
        admin_password: str,
        totp_secret: str = None,
    ):
        self.driver = driver
        self.tenant_domain = tenant_domain
        self.admin_email = admin_email
        self.admin_password = admin_password
        self.totp_secret = totp_secret
        self.access_token: Optional[str] = None
        self.executor = ThreadPoolExecutor(max_workers=1)

    async def get_token(self) -> str:
        """Get Graph API access token via device code flow."""

        logger.info("Starting Graph API device code auth for %s", self.tenant_domain)

        if msal is None:
            raise RuntimeError(
                "Missing dependency 'msal'. Install it with `pip install msal` or ensure "
                "backend requirements are installed."
            )

        loop = asyncio.get_event_loop()

        app = msal.PublicClientApplication(
            client_id=self.CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{self.tenant_domain}",
        )

        flow = await loop.run_in_executor(
            self.executor,
            lambda: app.initiate_device_flow(
                scopes=["https://graph.microsoft.com/User.ReadWrite.All"],
            ),
        )

        if "user_code" not in flow:
            raise Exception(f"Device flow failed: {flow.get('error_description')}")

        device_code = flow["user_code"]
        logger.info("Graph API device code: %s", device_code)

        success = await self._complete_device_login(device_code)
        if not success:
            raise Exception("Device code authentication failed")

        result = await loop.run_in_executor(
            self.executor,
            lambda: app.acquire_token_by_device_flow(flow),
        )

        if "access_token" in result:
            self.access_token = result["access_token"]
            logger.info("✓ Graph API token acquired!")
            return self.access_token

        raise Exception(f"Token acquisition failed: {result.get('error_description')}")

    async def _complete_device_login(self, device_code: str) -> bool:
        """Complete device code login using Selenium, handling MFA."""

        logger.info("Completing Graph device login with code: %s", device_code)

        try:
            # Navigate to device login page
            self.driver.get("https://microsoft.com/devicelogin")
            await asyncio.sleep(2)

            # Enter device code
            code_input = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.ID, "otc"))
            )
            code_input.clear()
            code_input.send_keys(device_code)

            # Click Next
            next_btn = self.driver.find_element(By.ID, "idSIButton9")
            next_btn.click()
            await asyncio.sleep(3)

            # SCREEN 1: "Pick an account"
            page_source = self.driver.page_source.lower()
            if "pick an account" in page_source or "choose an account" in page_source:
                logger.info("Account picker detected, clicking existing account...")
                try:
                    account_tile = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, "div.table"))
                    )
                    account_tile.click()
                    await asyncio.sleep(3)
                except Exception:
                    try:
                        first_account = self.driver.find_element(By.CSS_SELECTOR, "[data-test-id]")
                        first_account.click()
                        await asyncio.sleep(3)
                    except Exception:
                        pass

            # SCREEN 2: "Are you trying to sign in to..."
            await asyncio.sleep(2)
            page_source = self.driver.page_source.lower()
            if "are you trying to sign in" in page_source or "permissions requested" in page_source:
                logger.info("Consent screen detected, clicking Continue...")
                try:
                    continue_btn = WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable((By.ID, "idSIButton9"))
                    )
                    continue_btn.click()
                    await asyncio.sleep(3)
                except Exception as e:
                    logger.warning("Continue button: %s", e)

            # SCREEN 3: Password entry (if session expired)
            page_source = self.driver.page_source.lower()
            if "enter password" in page_source or "passwd" in self.driver.page_source:
                logger.info("Password entry detected...")
                try:
                    pwd_input = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.NAME, "passwd"))
                    )
                    pwd_input.clear()
                    pwd_input.send_keys(self.admin_password)
                    submit_btn = self.driver.find_element(By.ID, "idSIButton9")
                    submit_btn.click()
                    await asyncio.sleep(3)
                except Exception:
                    pass

            # SCREEN 4: MFA/TOTP
            await self._handle_mfa()

            # SCREEN 5: "Stay signed in?"
            await asyncio.sleep(2)
            try:
                page_source = self.driver.page_source.lower()
                if "stay signed in" in page_source:
                    yes_btn = self.driver.find_element(By.ID, "idSIButton9")
                    yes_btn.click()
                    await asyncio.sleep(2)
            except Exception:
                pass

            # Check for success
            await asyncio.sleep(3)
            page_source = self.driver.page_source.lower()
            if (
                "you have signed in" in page_source
                or "you're signed in" in page_source
                or "close this window" in page_source
            ):
                logger.info("✓ Graph device code authentication successful!")
                return True

            # Try one more continue/confirm button
            try:
                final_btn = self.driver.find_element(By.ID, "idSIButton9")
                final_btn.click()
                await asyncio.sleep(2)
            except Exception:
                pass

            return True

        except Exception as e:
            logger.error("Graph device login failed: %s", e)
            return False

    async def _handle_mfa(self):
        """Handle MFA/TOTP if required."""

        await asyncio.sleep(2)
        page_source = self.driver.page_source.lower()

        if "authenticator" in page_source or "verification code" in page_source or "enter code" in page_source:
            if self.totp_secret:
                import pyotp

                totp = pyotp.TOTP(self.totp_secret)
                code = totp.now()

                logger.info("Entering TOTP code for MFA")

                try:
                    totp_input = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.ID, "idTxtBx_SAOTCC_OTC"))
                    )
                    totp_input.clear()
                    totp_input.send_keys(code)

                    verify_btn = self.driver.find_element(By.ID, "idSubmit_SAOTCC_Continue")
                    verify_btn.click()
                    await asyncio.sleep(3)
                except Exception:
                    try:
                        totp_input = self.driver.find_element(By.NAME, "otc")
                        totp_input.clear()
                        totp_input.send_keys(code)

                        verify_btn = self.driver.find_element(By.ID, "idSIButton9")
                        verify_btn.click()
                        await asyncio.sleep(3)
                    except Exception as e:
                        logger.warning("TOTP input failed: %s", e)


async def set_passwords_via_graph(
    access_token: str,
    mailboxes: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Set passwords and enable accounts for all mailboxes using Graph API."""

    results = {"success": [], "failed": []}

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        for mb in mailboxes:
            email = mb["email"]
            password = mb["password"]

            url = f"https://graph.microsoft.com/v1.0/users/{email}"
            body = {
                "passwordProfile": {
                    "password": password,
                    "forceChangePasswordNextSignIn": False,
                },
                "accountEnabled": True,
            }

            try:
                response = await client.patch(url, json=body, headers=headers)

                if response.status_code in [200, 204]:
                    results["success"].append(email)
                    logger.info("  ✓ Password set + enabled: %s", email)
                else:
                    results["failed"].append({"email": email, "error": response.text})
                    logger.error("  ✗ Failed: %s - %s", email, response.status_code)
            except Exception as e:
                results["failed"].append({"email": email, "error": str(e)})
                logger.error("  ✗ Failed: %s - %s", email, e)

            await asyncio.sleep(0.2)  # Rate limiting

    return results