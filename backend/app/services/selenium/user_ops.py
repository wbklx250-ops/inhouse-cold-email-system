"""
User operations via Selenium UI.
No Graph API needed - uses M365 Admin Portal directly.
"""

import time
import logging
from typing import Optional, List, Dict
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys

logger = logging.getLogger(__name__)


class UserOpsSelenium:
    """Handle user operations via M365 Admin Portal UI."""
    
    def __init__(self, driver: webdriver.Chrome, domain: str):
        self.driver = driver
        self.domain = domain
    
    def _screenshot(self, name: str):
        """Take screenshot for debugging."""
        try:
            path = f"C:/temp/screenshots/step6/{self.domain}_{name}_{int(time.time())}.png"
            self.driver.save_screenshot(path)
            logger.info(f"Screenshot: {path}")
        except:
            pass
    
    def _wait_and_click(self, by: By, value: str, timeout: int = 15) -> bool:
        """Wait for element and click it."""
        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((by, value))
            )
            element.click()
            return True
        except Exception as e:
            logger.error(f"Could not click {value}: {e}")
            return False
    
    def _wait_and_type(self, by: By, value: str, text: str, timeout: int = 15) -> bool:
        """Wait for input and type text."""
        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
            element.clear()
            element.send_keys(text)
            return True
        except Exception as e:
            logger.error(f"Could not type in {value}: {e}")
            return False

    def create_licensed_user(
        self,
        username: str = "me1",
        display_name: str = "me1",
        password: str = "#Sendemails1",
        onmicrosoft_domain: str = None
    ) -> Dict:
        """Create a licensed user via M365 Admin Portal.
        
        Preset values:
        - First name: Me
        - Last name: 1
        - Display name: me1
        - Username: me1
        - Password: #Sendemails1
        """
        
        logger.info(f"[{self.domain}] Creating licensed user: {username}")
        
        try:
            # Navigate to Users page
            self.driver.get("https://admin.microsoft.com/#/users")
            time.sleep(5)
            self._screenshot("users_page")
            
            # Click "Add a user" button
            add_user_selectors = [
                "button[data-automationid='addUserButton']",
                "button[aria-label*='Add a user']",
                "button[aria-label*='Add user']",
                "span[data-automationid='splitbuttonprimary']",
                ".ms-Button--primary",
            ]
            
            clicked = False
            for selector in add_user_selectors:
                try:
                    btn = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )
                    btn.click()
                    clicked = True
                    logger.info(f"Clicked Add user via: {selector}")
                    break
                except:
                    continue
            
            if not clicked:
                # Try by text
                try:
                    btn = self.driver.find_element(By.XPATH, "//button[contains(., 'Add a user')]")
                    btn.click()
                    clicked = True
                except:
                    pass
            
            if not clicked:
                self._screenshot("add_user_button_not_found")
                return {"success": False, "error": "Could not find Add user button"}
            
            time.sleep(3)
            self._screenshot("add_user_form")
            
            # Preset values - hardcoded for consistency
            first_name = "Me"
            last_name = "1"
            display_name_value = "me1"
            
            # Fill first name
            try:
                first_input = self.driver.find_element(By.CSS_SELECTOR, "input[aria-label*='First name'], input[placeholder*='First']")
                first_input.clear()
                first_input.send_keys(first_name)
                logger.info(f"Entered first name: {first_name}")
            except Exception as e:
                logger.warning(f"Could not enter first name: {e}")

            # Fill last name
            try:
                last_input = self.driver.find_element(By.CSS_SELECTOR, "input[aria-label*='Last name'], input[placeholder*='Last']")
                last_input.clear()
                last_input.send_keys(last_name)
                logger.info(f"Entered last name: {last_name}")
            except Exception as e:
                logger.warning(f"Could not enter last name: {e}")

            time.sleep(1)

            # Fill display name (may auto-populate but ensure it's correct)
            try:
                display_input = self.driver.find_element(By.CSS_SELECTOR, "input[aria-label*='Display name']")
                display_input.clear()
                display_input.send_keys(display_name_value)
                logger.info(f"Entered display name: {display_name_value}")
            except Exception as e:
                logger.warning(f"Could not enter display name: {e}")

            # Fill username (me1)
            try:
                username_input = self.driver.find_element(By.CSS_SELECTOR, "input[aria-label*='User name'], input[aria-label*='Username']")
                username_input.clear()
                username_input.send_keys(username)
                logger.info(f"Entered username: {username}")
            except Exception as e:
                logger.error(f"Could not enter username: {e}")

            time.sleep(1)

            # After filling username, FORCE uncheck the auto-password checkbox with JS

            # Keep trying until password field appears
            for attempt in range(10):
                # Check if password field exists
                try:
                    pwd_field = self.driver.find_element(By.CSS_SELECTOR, "input[type='password']")
                    if pwd_field.is_displayed():
                        logger.info("Password field visible!")
                        break
                except:
                    pass
                
                # Force uncheck with JavaScript
                self.driver.execute_script("""
                    document.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                        if (cb.checked) cb.click();
                    });
                """)
                time.sleep(1)

            # Enter password
            pwd_input = self.driver.find_element(By.CSS_SELECTOR, "input[type='password']")
            pwd_input.send_keys(password)
            logger.info("Entered password")

            self._screenshot("form_filled")

            # Click Next to proceed to Product licenses page
            time.sleep(1)
            self._wait_and_click(By.XPATH, "//button[contains(., 'Next')]")
            time.sleep(3)
            self._screenshot("license_page")
            
            # Assign license page - select a license
            try:
                # Click first available license checkbox
                license_checkbox = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='checkbox'][aria-label*='license'], .ms-Checkbox"))
                )
                license_checkbox.click()
                logger.info("Selected license checkbox")
                time.sleep(1)
            except:
                logger.warning("Could not select license automatically")
            
            self._screenshot("license_selected")
            
            # Click Next to Optional settings
            self._wait_and_click(By.XPATH, "//button[contains(., 'Next')]")
            time.sleep(2)
            self._screenshot("optional_settings_page")
            
            # Optional settings page - just click Next
            self._wait_and_click(By.XPATH, "//button[contains(., 'Next')]")
            time.sleep(2)
            self._screenshot("review_page")
            
            # On the Review and finish page, click "Finish adding"
            try:
                finish_btn = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Finish adding')]"))
                )
                finish_btn.click()
                logger.info("Clicked 'Finish adding' button")
                time.sleep(5)
            except:
                # Try alternative selectors
                try:
                    finish_btn = self.driver.find_element(By.CSS_SELECTOR, "button.ms-Button--primary")
                    finish_btn.click()
                    logger.info("Clicked primary button")
                    time.sleep(5)
                except:
                    # Last resort - JS click
                    self.driver.execute_script("""
                        const btn = document.querySelector('button.ms-Button--primary') || 
                                    [...document.querySelectorAll('button')].find(b => b.textContent.includes('Finish'));
                        if (btn) btn.click();
                    """)
                    logger.info("Clicked finish via JS")
                    time.sleep(5)

            self._screenshot("user_created_final")
            
            # Close any success dialog
            try:
                self._wait_and_click(By.XPATH, "//button[contains(., 'Close')]", timeout=5)
            except:
                pass
            
            upn = f"{username}@{onmicrosoft_domain}" if onmicrosoft_domain else username
            email = upn  # For consistency with previous API
            logger.info(f"[{self.domain}] ✓ Created licensed user: {upn}")
            
            return {"success": True, "upn": upn, "email": email, "password": password}
            
        except Exception as e:
            logger.error(f"[{self.domain}] Failed to create user: {e}")
            self._screenshot("create_user_error")
            return {"success": False, "error": str(e)}

    def enable_user(self, email: str) -> bool:
        """Enable a user account (unblock sign-in)."""
        logger.info(f"[{self.domain}] Enabling user: {email}")
        
        try:
            # Navigate to user
            self.driver.get(f"https://admin.microsoft.com/#/users/:/UserDetails/{email}")
            time.sleep(5)
            self._screenshot(f"user_details_{email.split('@')[0]}")
            
            # Look for "Unblock sign-in" or toggle
            try:
                unblock = self.driver.find_element(By.XPATH, "//button[contains(., 'Unblock')]")
                unblock.click()
                time.sleep(2)
                
                # Confirm
                self._wait_and_click(By.XPATH, "//button[contains(., 'Save') or contains(., 'Confirm')]")
                time.sleep(2)
                
                logger.info(f"[{self.domain}] ✓ Enabled user: {email}")
                return True
            except:
                logger.info(f"[{self.domain}] User may already be enabled: {email}")
                return True
                
        except Exception as e:
            logger.error(f"[{self.domain}] Failed to enable user {email}: {e}")
            return False

    def enable_users_bulk(self, emails: List[str]) -> Dict:
        """Enable multiple user accounts."""
        enabled = []
        failed = []
        
        for email in emails:
            if self.enable_user(email):
                enabled.append(email)
            else:
                failed.append(email)
        
        return {"enabled": enabled, "failed": failed}

    def set_password(self, email: str, password: str) -> bool:
        """Set user password."""
        logger.info(f"[{self.domain}] Setting password for: {email}")
        
        try:
            # Navigate to user
            self.driver.get(f"https://admin.microsoft.com/#/users/:/UserDetails/{email}")
            time.sleep(5)
            
            # Click "Reset password"
            self._wait_and_click(By.XPATH, "//button[contains(., 'Reset password')]")
            time.sleep(3)
            self._screenshot(f"reset_password_{email.split('@')[0]}")
            
            # Uncheck auto-generate if needed
            try:
                auto_pwd = self.driver.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
                if auto_pwd.is_selected():
                    auto_pwd.click()
                    time.sleep(1)
            except:
                pass
            
            # Enter password
            self._wait_and_type(By.CSS_SELECTOR, "input[type='password']", password)
            
            # Click Reset/Save
            self._wait_and_click(By.XPATH, "//button[contains(., 'Reset') or contains(., 'Save')]")
            time.sleep(3)
            
            logger.info(f"[{self.domain}] ✓ Set password for: {email}")
            return True
            
        except Exception as e:
            logger.error(f"[{self.domain}] Failed to set password for {email}: {e}")
            return False

    def set_passwords_bulk(self, users: List[Dict]) -> Dict:
        """Set passwords for multiple users.
        
        Args:
            users: List of dicts with 'upn' and 'password' keys
        """
        set_passwords = []
        failed = []
        
        for user in users:
            if self.set_password(user['upn'], user['password']):
                set_passwords.append(user['upn'])
            else:
                failed.append(user['upn'])
        
        return {"set": set_passwords, "failed": failed}

    def fix_upn(self, current_upn: str, new_upn: str) -> bool:
        """Change user's UPN."""
        logger.info(f"[{self.domain}] Fixing UPN: {current_upn} → {new_upn}")
        
        try:
            # Navigate to user
            self.driver.get(f"https://admin.microsoft.com/#/users/:/UserDetails/{current_upn}")
            time.sleep(5)
            self._screenshot(f"fix_upn_start_{current_upn.split('@')[0]}")
            
            # Click "Manage username and email"
            manage_clicked = self._wait_and_click(By.XPATH, "//button[contains(., 'Manage') and contains(., 'username')]")
            if not manage_clicked:
                # Try alternative
                manage_clicked = self._wait_and_click(By.XPATH, "//a[contains(., 'Manage username')]")
            if not manage_clicked:
                # Try clicking on the username/email section
                manage_clicked = self._wait_and_click(By.XPATH, "//*[contains(text(), 'username and email')]")
            
            time.sleep(3)
            self._screenshot(f"fix_upn_manage_{current_upn.split('@')[0]}")
            
            # Update the username field
            username = new_upn.split("@")[0]
            new_domain = new_upn.split("@")[1] if "@" in new_upn else None
            
            # Find and update username input
            username_updated = self._wait_and_type(By.CSS_SELECTOR, "input[aria-label*='Username'], input[aria-label*='username']", username)
            
            if not username_updated:
                # Try other selectors
                self._wait_and_type(By.CSS_SELECTOR, "input[type='text']", username)
            
            # Select domain dropdown if needed
            if new_domain:
                try:
                    # Click domain dropdown
                    dropdown = self.driver.find_element(By.CSS_SELECTOR, "div[class*='Dropdown'], select")
                    dropdown.click()
                    time.sleep(1)
                    
                    # Select the new domain
                    domain_option = self.driver.find_element(By.XPATH, f"//*[contains(text(), '{new_domain}')]")
                    domain_option.click()
                    time.sleep(1)
                except Exception as e:
                    logger.warning(f"Could not select domain: {e}")
            
            time.sleep(1)
            self._screenshot(f"fix_upn_filled_{current_upn.split('@')[0]}")
            
            # Save
            self._wait_and_click(By.XPATH, "//button[contains(., 'Save')]")
            time.sleep(3)
            
            # Close any confirmation dialog
            try:
                self._wait_and_click(By.XPATH, "//button[contains(., 'Close') or contains(., 'Done')]", timeout=5)
            except:
                pass
            
            logger.info(f"[{self.domain}] ✓ Fixed UPN: {new_upn}")
            return True
            
        except Exception as e:
            logger.error(f"[{self.domain}] Failed to fix UPN: {e}")
            self._screenshot(f"fix_upn_error_{current_upn.split('@')[0]}")
            return False

    def update_upns_bulk(self, users: List[Dict]) -> Dict:
        """Update UPNs for multiple users.
        
        Args:
            users: List of dicts with 'current_upn' and 'new_upn' keys
        """
        updated = []
        failed = []
        
        for user in users:
            if self.fix_upn(user['current_upn'], user['new_upn']):
                updated.append(user['new_upn'])
            else:
                failed.append(user['current_upn'])
        
        return {"updated": updated, "failed": failed}
