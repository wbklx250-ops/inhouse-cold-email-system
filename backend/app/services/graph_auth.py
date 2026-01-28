"""
Graph API Authentication using Device Code Flow.

Uses the Azure CLI client ID (pre-consented in all tenants).
"""

import logging
import time
from typing import Optional

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logger = logging.getLogger(__name__)

# Use Azure CLI client ID - pre-consented in all tenants
CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"


def get_graph_token_device_code(driver: webdriver.Chrome, tenant_domain: str) -> Optional[str]:
    """
    Get Graph token using Device Code Flow.

    Since Selenium is already logged in, we can auto-complete the device login.
    """
    logger.info("Getting Graph token via Device Code Flow for %s", tenant_domain)

    # Step 1: Request device code
    device_code_url = f"https://login.microsoftonline.com/{tenant_domain}/oauth2/v2.0/devicecode"

    payload = {
        "client_id": CLIENT_ID,
        "scope": (
            "https://graph.microsoft.com/User.ReadWrite.All "
            "https://graph.microsoft.com/Directory.ReadWrite.All "
            "offline_access"
        ),
    }

    try:
        response = requests.post(device_code_url, data=payload, timeout=30)
        if response.status_code != 200:
            logger.error("Device code request failed: %s", response.text)
            return None

        data = response.json()
        user_code = data.get("user_code")
        device_code = data.get("device_code")
        verification_uri = data.get("verification_uri", "https://microsoft.com/devicelogin")
        interval = data.get("interval", 5)
        expires_in = data.get("expires_in", 900)

        logger.info("Got device code. User code: %s", user_code)

        # Step 2: Navigate to device login page in authenticated browser
        original_url = driver.current_url
        logger.info("Navigating to %s...", verification_uri)

        driver.get(verification_uri)
        time.sleep(3)

        # Step 3: Enter the user code
        try:
            # Find code input field
            code_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "otc"))
            )
            code_input.clear()
            code_input.send_keys(user_code)
            logger.info("Entered user code: %s", user_code)

            # Click Next button
            next_btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.ID, "idSIButton9"))
            )
            next_btn.click()
            time.sleep(5)

            # Handle "Pick an account" page - click the signed-in account
            try:
                # Look for the account tile (the signed-in user)
                account_tile = WebDriverWait(driver, 15).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".table[data-test-id]"))
                )
                account_tile.click()
                logger.info("Clicked signed-in account")
                time.sleep(5)
            except Exception:
                # Try alternative selectors
                try:
                    # Click on the account row
                    account = driver.find_element(
                        By.XPATH,
                        "//div[contains(@class, 'table')]//div[contains(@data-test-id, 'admin@') or contains(text(), 'Signed in')]",
                    )
                    account.click()
                    logger.info("Clicked account via alternative selector")
                    time.sleep(5)
                except Exception:
                    try:
                        # Click first account in list
                        account = driver.find_element(By.CSS_SELECTOR, "[data-test-id*='@']")
                        account.click()
                        logger.info("Clicked first account")
                        time.sleep(5)
                    except Exception:
                        logger.warning(
                            "Could not find account to click, may proceed automatically"
                        )

            # Should auto-approve since already logged in
            # Look for Continue or confirmation
            try:
                continue_btn = WebDriverWait(driver, 15).until(
                    EC.element_to_be_clickable((By.ID, "idSIButton9"))
                )
                continue_btn.click()
                logger.info("Clicked Continue button")
                time.sleep(5)
            except Exception:
                pass  # May not need to click anything else

            # Check for success message
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located(
                        (
                            By.XPATH,
                            "//*[contains(text(), 'signed in') "
                            "or contains(text(), 'success') "
                            "or contains(text(), 'close')]",
                        )
                    )
                )
                logger.info("Device login completed successfully")
            except Exception:
                logger.warning("Could not confirm success, proceeding to poll for token...")

        except Exception as exc:
            logger.error("Failed to enter device code: %s", exc)
            driver.get(original_url)
            return None

        # Step 4: Poll for token
        token_url = f"https://login.microsoftonline.com/{tenant_domain}/oauth2/v2.0/token"

        token_payload = {
            "client_id": CLIENT_ID,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": device_code,
        }

        logger.info("Polling for token...")
        max_attempts = expires_in // interval

        for attempt in range(max_attempts):
            time.sleep(interval)

            response = requests.post(token_url, data=token_payload, timeout=30)
            data = response.json()

            if "access_token" in data:
                token = data["access_token"]
                logger.info("✓ SUCCESS! Got Graph token via Device Code Flow, length: %s", len(token))
                driver.get(original_url)
                time.sleep(2)
                return token

            error = data.get("error")
            if error == "authorization_pending":
                logger.debug("Polling attempt %s... waiting for authorization", attempt + 1)
                continue
            if error == "authorization_declined":
                logger.error("User declined authorization")
                break
            if error == "expired_token":
                logger.error("Device code expired")
                break

            logger.warning("Unexpected response: %s", data)

        driver.get(original_url)
        time.sleep(2)
        logger.error("Device code flow timed out")
        return None

    except Exception as exc:
        logger.error("Device code flow failed: %s", exc)
        import traceback

        logger.error(traceback.format_exc())
        return None