"""
Selenium UI Service for User Operations

Handles user-related operations via M365 Admin Portal UI:
- Create licensed user (me1)
- Assign license
- Enable accounts
- Set passwords
- Fix UPNs

These operations require Graph API which we couldn't extract tokens for,
so we fall back to reliable UI automation.
"""

import time
import logging
from typing import Optional, Dict, List, Any
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

logger = logging.getLogger(__name__)

# Screenshot directory
SCREENSHOT_DIR = "C:/temp/screenshots/step6"


class UserOperationsService:
    """Handle user operations via M365 Admin Portal UI."""

    def __init__(self, driver: webdriver.Chrome):
        """
        Initialize with an authenticated Selenium driver.

        Args:
            driver: Chrome driver already logged into M365 Admin Portal
        """
        self.driver = driver
        self.wait = WebDriverWait(driver, 15)

    def _screenshot(self, name: str):
        """Save a screenshot for debugging."""
        import os

        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        path = f"{SCREENSHOT_DIR}/{name}_{int(time.time())}.png"
        try:
            self.driver.save_screenshot(path)
            logger.debug(f"Screenshot saved: {path}")
        except Exception:
            pass

    def _click_element(self, selectors: List[tuple], description: str) -> bool:
        """Try multiple selectors to click an element."""
        for by, selector in selectors:
            try:
                element = self.wait.until(EC.element_to_be_clickable((by, selector)))
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});", element
                )
                time.sleep(0.3)
                element.click()
                logger.debug(f"Clicked: {description}")
                return True
            except Exception:
                continue
        logger.warning(f"Could not click: {description}")
        return False

    def _fill_input(self, selectors: List[tuple], value: str, description: str) -> bool:
        """Try multiple selectors to fill an input."""
        for by, selector in selectors:
            try:
                element = self.wait.until(EC.presence_of_element_located((by, selector)))
                element.clear()
                element.send_keys(value)
                logger.debug(f"Filled: {description}")
                return True
            except Exception:
                continue
        logger.warning(f"Could not fill: {description}")
        return False

    # =========================================================================
    # CREATE LICENSED USER (me1)
    # =========================================================================

    def create_licensed_user(
        self,
        onmicrosoft_domain: str,
        display_name: str = "Licensed User",
        password: str = "#Sendemails1",
    ) -> Dict[str, Any]:
        """
        Create the licensed user (me1) via Admin Portal UI.

        Args:
            onmicrosoft_domain: The tenant's onmicrosoft.com domain
            display_name: Display name for the user
            password: Password for the user

        Returns:
            Dict with success status and user details
        """
        username = "me1"
        email = f"{username}@{onmicrosoft_domain}"

        logger.info(f"Creating licensed user: {email}")

        try:
            # Navigate to Users > Active users
            self.driver.get("https://admin.microsoft.com/#/users")
            time.sleep(3)
            self._screenshot("users_page")

            # Click "Add a user" button
            add_user_clicked = self._click_element(
                [
                    (By.XPATH, "//button[contains(text(), 'Add a user')]") ,
                    (By.XPATH, "//span[contains(text(), 'Add a user')]/parent::button"),
                    (By.CSS_SELECTOR, "button[data-automationid='addUserButton']"),
                    (By.XPATH, "//button[contains(@class, 'addUser')]"),
                ],
                "Add a user button",
            )

            if not add_user_clicked:
                self._screenshot("add_user_not_found")
                return {"success": False, "error": "Could not find Add User button"}

            time.sleep(2)
            self._screenshot("add_user_form")

            # Fill in user details
            # First name
            self._fill_input(
                [
                    (By.NAME, "firstName"),
                    (By.ID, "firstName"),
                    (By.XPATH, "//input[@aria-label='First name']"),
                ],
                "Licensed",
                "First name",
            )

            # Last name
            self._fill_input(
                [
                    (By.NAME, "lastName"),
                    (By.ID, "lastName"),
                    (By.XPATH, "//input[@aria-label='Last name']"),
                ],
                "User",
                "Last name",
            )

            # Display name (might auto-fill)
            time.sleep(0.5)

            # Username
            self._fill_input(
                [
                    (By.NAME, "userName"),
                    (By.ID, "userName"),
                    (By.XPATH, "//input[@aria-label='Username']"),
                    (By.XPATH, "//input[contains(@placeholder, 'Username')]"),
                ],
                username,
                "Username",
            )

            time.sleep(1)
            self._screenshot("user_details_filled")

            # Click Next
            self._click_element(
                [
                    (By.XPATH, "//button[contains(text(), 'Next')]"),
                    (By.XPATH, "//button[@type='submit']"),
                ],
                "Next button",
            )

            time.sleep(2)

            # Product licenses page - select a license
            self._screenshot("license_page")

            # Try to find and check a license checkbox
            # Look for any available license
            license_checked = self._click_element(
                [
                    (By.XPATH, "//input[@type='checkbox' and contains(@aria-label, 'Microsoft 365')]"),
                    (By.XPATH, "//input[@type='checkbox' and contains(@aria-label, 'Office 365')]"),
                    (By.XPATH, "//div[contains(@class, 'license')]//input[@type='checkbox']"),
                    (By.CSS_SELECTOR, "input[type='checkbox'][aria-label*='license']"),
                ],
                "License checkbox",
            )

            if not license_checked:
                # Try clicking on the license row itself
                self._click_element(
                    [
                        (
                            By.XPATH,
                            "//div[contains(text(), 'Microsoft 365')]/ancestor::div[contains(@class, 'row')]",
                        ),
                        (
                            By.XPATH,
                            "//span[contains(text(), 'Microsoft 365')]/ancestor::div[contains(@class, 'license')]",
                        ),
                    ],
                    "License row",
                )

            time.sleep(1)
            self._screenshot("license_selected")

            # Click Next
            self._click_element(
                [(By.XPATH, "//button[contains(text(), 'Next')]")],
                "Next button (after license)",
            )

            time.sleep(2)

            # Optional settings page - just click Next
            self._screenshot("optional_settings")
            self._click_element(
                [(By.XPATH, "//button[contains(text(), 'Next')]")],
                "Next button (optional settings)",
            )

            time.sleep(2)

            # Review page - set password
            self._screenshot("review_page")

            # Look for password options
            # Select "Let me create the password"
            self._click_element(
                [
                    (By.XPATH, "//input[@type='radio' and contains(@aria-label, 'create')]"),
                    (
                        By.XPATH,
                        "//label[contains(text(), 'Let me create')]/preceding-sibling::input",
                    ),
                    (By.XPATH, "//span[contains(text(), 'Let me create')]/parent::label//input"),
                ],
                "Create password option",
            )

            time.sleep(0.5)

            # Fill password
            self._fill_input(
                [
                    (By.XPATH, "//input[@type='password']"),
                    (By.NAME, "password"),
                    (By.ID, "password"),
                ],
                password,
                "Password field",
            )

            # Uncheck "Require password change"
            self._click_element(
                [
                    (By.XPATH, "//input[@type='checkbox' and contains(@aria-label, 'change')]"),
                    (By.XPATH, "//label[contains(text(), 'Require')]/input"),
                ],
                "Uncheck require password change",
            )

            time.sleep(1)
            self._screenshot("password_set")

            # Click "Finish adding" or "Add"
            self._click_element(
                [
                    (By.XPATH, "//button[contains(text(), 'Finish adding')]") ,
                    (By.XPATH, "//button[contains(text(), 'Add')]") ,
                    (By.XPATH, "//button[@type='submit']"),
                ],
                "Finish adding button",
            )

            time.sleep(3)
            self._screenshot("user_created")

            # Check for success message
            page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            if (
                "has been added" in page_text
                or "successfully" in page_text
                or email.lower() in page_text
            ):
                logger.info(f"✓ Licensed user created: {email}")
                return {
                    "success": True,
                    "email": email,
                    "password": password,
                    "display_name": display_name,
                }
            # Check for "already exists" error
            if "already exists" in page_text or "already in use" in page_text:
                logger.info(f"User {email} already exists")
                return {
                    "success": True,
                    "email": email,
                    "password": password,
                    "note": "User already existed",
                }

            self._screenshot("user_creation_failed")
            return {
                "success": False,
                "error": "User creation may have failed - check screenshots",
            }

        except Exception as e:
            logger.error(f"Error creating licensed user: {e}")
            self._screenshot("user_creation_error")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # ENABLE USER ACCOUNT
    # =========================================================================

    def enable_user_account(self, user_email: str) -> Dict[str, Any]:
        """
        Enable a user account (unblock sign-in).

        Shared mailbox accounts are blocked by default.
        """
        logger.info(f"Enabling account: {user_email}")

        try:
            # Navigate to the user
            # URL encode the email for the URL
            encoded_email = user_email.replace("@", "%40")
            self.driver.get(f"https://admin.microsoft.com/#/users/:{encoded_email}")
            time.sleep(3)
            self._screenshot(f"user_detail_{user_email.split('@')[0]}")

            # Look for "Unblock sign-in" or similar
            # First check if already enabled
            page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            if "sign-in allowed" in page_text or "sign-in: allowed" in page_text:
                logger.info(f"Account {user_email} already enabled")
                return {"success": True, "note": "Already enabled"}

            # Click "Block sign-in" to toggle (or find enable button)
            self._click_element(
                [
                    (By.XPATH, "//button[contains(text(), 'Unblock')]") ,
                    (By.XPATH, "//span[contains(text(), 'Unblock')]/parent::button"),
                    (By.XPATH, "//button[contains(text(), 'Edit sign-in')]") ,
                ],
                "Unblock/Enable button",
            )

            time.sleep(2)

            # If a dialog opens, confirm
            self._click_element(
                [
                    (By.XPATH, "//button[contains(text(), 'Save')]") ,
                    (By.XPATH, "//button[contains(text(), 'Confirm')]") ,
                    (By.XPATH, "//button[contains(text(), 'Yes')]") ,
                ],
                "Confirm button",
            )

            time.sleep(2)

            logger.info(f"✓ Account enabled: {user_email}")
            return {"success": True}

        except Exception as e:
            logger.error(f"Error enabling account {user_email}: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # SET PASSWORD
    # =========================================================================

    def set_user_password(self, user_email: str, password: str) -> Dict[str, Any]:
        """Set/reset a user's password."""
        logger.info(f"Setting password for: {user_email}")

        try:
            # Navigate to user
            encoded_email = user_email.replace("@", "%40")
            self.driver.get(f"https://admin.microsoft.com/#/users/:{encoded_email}")
            time.sleep(3)

            # Click "Reset password"
            self._click_element(
                [
                    (By.XPATH, "//button[contains(text(), 'Reset password')]") ,
                    (By.XPATH, "//span[contains(text(), 'Reset password')]/parent::button"),
                ],
                "Reset password button",
            )

            time.sleep(2)
            self._screenshot(f"reset_password_{user_email.split('@')[0]}")

            # Select "Let me create the password"
            self._click_element(
                [
                    (By.XPATH, "//input[@type='radio' and contains(@aria-label, 'create')]") ,
                    (By.XPATH, "//label[contains(text(), 'Let me create')]/input"),
                ],
                "Create password option",
            )

            time.sleep(0.5)

            # Fill password
            self._fill_input(
                [
                    (By.XPATH, "//input[@type='password']"),
                    (By.NAME, "password"),
                ],
                password,
                "Password field",
            )

            # Uncheck require change
            try:
                checkbox = self.driver.find_element(
                    By.XPATH,
                    "//input[@type='checkbox' and contains(@aria-label, 'change')]",
                )
                if checkbox.is_selected():
                    checkbox.click()
            except Exception:
                pass

            # Click Reset
            self._click_element(
                [
                    (By.XPATH, "//button[contains(text(), 'Reset')]") ,
                    (By.XPATH, "//button[@type='submit']"),
                ],
                "Reset button",
            )

            time.sleep(2)

            logger.info(f"✓ Password set for: {user_email}")
            return {"success": True}

        except Exception as e:
            logger.error(f"Error setting password for {user_email}: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # FIX UPN
    # =========================================================================

    def fix_user_upn(self, current_upn: str, target_email: str) -> Dict[str, Any]:
        """
        Fix a user's UPN to match their email address.

        Args:
            current_upn: Current UPN (might be ...@tenant.onmicrosoft.com)
            target_email: Target email/UPN (e.g., jack@domain.com)
        """
        logger.info(f"Fixing UPN: {current_upn} -> {target_email}")

        try:
            # Navigate to user
            encoded_email = current_upn.replace("@", "%40")
            self.driver.get(f"https://admin.microsoft.com/#/users/:{encoded_email}")
            time.sleep(3)

            # Click on username/UPN to edit
            self._click_element(
                [
                    (By.XPATH, "//button[contains(text(), 'Manage username')]") ,
                    (By.XPATH, "//span[contains(text(), 'username')]/parent::button"),
                    (By.XPATH, f"//span[contains(text(), '{current_upn}')]/parent::button"),
                ],
                "Manage username button",
            )

            time.sleep(2)
            self._screenshot(f"edit_upn_{current_upn.split('@')[0]}")

            # Clear and fill new username
            username_part = target_email.split("@")[0]

            self._fill_input(
                [
                    (By.XPATH, "//input[@aria-label='Username']"),
                    (By.NAME, "userName"),
                ],
                username_part,
                "Username field",
            )

            # Select the correct domain from dropdown
            domain_part = target_email.split("@")[1]
            self._click_element(
                [
                    (By.XPATH, f"//option[contains(text(), '{domain_part}')]") ,
                    (By.XPATH, f"//div[contains(text(), '{domain_part}')]") ,
                ],
                "Domain dropdown",
            )

            # Save
            self._click_element(
                [
                    (By.XPATH, "//button[contains(text(), 'Save')]") ,
                    (By.XPATH, "//button[@type='submit']"),
                ],
                "Save button",
            )

            time.sleep(2)

            logger.info(f"✓ UPN fixed: {target_email}")
            return {"success": True}

        except Exception as e:
            logger.error(f"Error fixing UPN {current_upn}: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # BULK OPERATIONS
    # =========================================================================

    def enable_accounts_bulk(self, user_emails: List[str]) -> Dict[str, Any]:
        """Enable multiple user accounts."""
        results = {"enabled": [], "failed": []}

        for email in user_emails:
            result = self.enable_user_account(email)
            if result.get("success"):
                results["enabled"].append(email)
            else:
                results["failed"].append({"email": email, "error": result.get("error")})

        return results

    def set_passwords_bulk(self, users: List[Dict[str, str]]) -> Dict[str, Any]:
        """Set passwords for multiple users."""
        results = {"set": [], "failed": []}

        for user in users:
            result = self.set_user_password(user["email"], user["password"])
            if result.get("success"):
                results["set"].append(user["email"])
            else:
                results["failed"].append({"email": user["email"], "error": result.get("error")})

        return results

    def fix_upns_bulk(self, users: List[Dict[str, str]]) -> Dict[str, Any]:
        """Fix UPNs for multiple users."""
        results = {"fixed": [], "failed": []}

        for user in users:
            result = self.fix_user_upn(user["current_upn"], user["target_email"])
            if result.get("success"):
                results["fixed"].append(user["target_email"])
            else:
                results["failed"].append({"email": user["target_email"], "error": result.get("error")})

        return results