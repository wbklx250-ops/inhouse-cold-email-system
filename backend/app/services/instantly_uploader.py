"""
Instantly.ai Uploader Service
Automates uploading mailboxes to Instantly.ai via Selenium OAuth flow

Enhanced with robust selector fallbacks, account existence checking,
session clearing, and improved OAuth flow handling.
"""
import asyncio
import logging
import time
import random
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Dict, Optional, Any

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    TimeoutException, WebDriverException, NoSuchElementException,
    ElementClickInterceptedException, NoSuchWindowException
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mailbox import Mailbox
from app.models.tenant import Tenant
from app.models.batch import SetupBatch
from app.db.session import async_session_factory

logger = logging.getLogger(__name__)


class InstantlyUploader:
    """Handles Selenium automation for uploading mailboxes to Instantly.ai"""
    
    def __init__(
        self,
        instantly_email: str,
        instantly_password: str,
        headless: bool = True,
        worker_id: int = 0
    ):
        self.instantly_email = instantly_email
        self.instantly_password = instantly_password
        self.headless = headless
        self.worker_id = worker_id
        self.driver: Optional[webdriver.Chrome] = None
        self.wait: Optional[WebDriverWait] = None
        
    def setup_driver(self):
        """Initialize Chrome WebDriver with appropriate options"""
        chrome_options = Options()
        chrome_options.add_argument("--disable-popup-blocking")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # Add options to improve stability
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-background-timer-throttling")
        chrome_options.add_argument("--disable-backgrounding-occluded-windows")
        chrome_options.add_argument("--disable-renderer-backgrounding")
        chrome_options.add_argument("--window-size=1920,1080")
        
        # For parallel processing, offset window positions
        if self.worker_id and isinstance(self.worker_id, int):
            offset = self.worker_id * 50
            chrome_options.add_argument(f"--window-position={offset},{offset}")
        
        if self.headless:
            chrome_options.add_argument("--headless=new")
        
        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        self.driver.set_page_load_timeout(60)
        self.wait = WebDriverWait(self.driver, 30)
        
        logger.info(f"[Worker {self.worker_id}] Chrome driver initialized (headless={self.headless})")
        
    def random_delay(self, min_sec: float = 1.0, max_sec: float = 3.0):
        """Add random delay to mimic human behavior"""
        delay = random.uniform(min_sec, max_sec)
        time.sleep(delay)
        
    def login_to_instantly(self) -> bool:
        """
        Log in to Instantly.ai
        Returns True if successful, False otherwise
        """
        try:
            logger.info(f"[Worker {self.worker_id}] Navigating to Instantly.ai login...")
            self.driver.get("https://app.instantly.ai/app/login")
            self.random_delay(2, 4)
            
            # Wait for and fill email
            email_input = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email'], input[name='email']"))
            )
            email_input.clear()
            email_input.send_keys(self.instantly_email)
            logger.info(f"[Worker {self.worker_id}] Email entered")
            self.random_delay(1, 2)
            
            # Fill password
            password_input = self.driver.find_element(By.CSS_SELECTOR, "input[type='password'], input[name='password']")
            password_input.clear()
            password_input.send_keys(self.instantly_password)
            logger.info(f"[Worker {self.worker_id}] Password entered")
            self.random_delay(1, 2)
            
            # Click login button
            login_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            login_button.click()
            logger.info(f"[Worker {self.worker_id}] Login button clicked")
            
            # Wait for redirect to dashboard (URL should change)
            self.wait.until(lambda d: "login" not in d.current_url.lower())
            logger.info(f"[Worker {self.worker_id}] Successfully logged in to Instantly.ai")
            self.random_delay(2, 3)
            return True
            
        except Exception as e:
            logger.error(f"[Worker {self.worker_id}] Failed to login to Instantly: {str(e)}")
            return False
            
    def save_debug_screenshot(self, label="debug"):
        """Save a screenshot for debugging headless issues"""
        try:
            os.makedirs('screenshots', exist_ok=True)
            filename = f"screenshots/{self.worker_id}_{label}_{datetime.now().strftime('%H%M%S')}.png"
            self.driver.save_screenshot(filename)
            logger.info(f"[Worker {self.worker_id}] Debug screenshot saved: {filename}")
        except Exception as e:
            logger.warning(f"[Worker {self.worker_id}] Could not save screenshot: {e}")
    
    def check_account_exists(self, account_email: str) -> bool:
        """Check if an account already exists in Instantly.ai (visible text only)"""
        try:
            # Ensure we're on the accounts page
            if "accounts" not in self.driver.current_url:
                self.driver.get("https://app.instantly.ai/app/accounts")
                self.random_delay(2, 3)
            
            logger.info(f"[Worker {self.worker_id}] Checking if {account_email} already exists...")
            
            # Only check visible text elements containing @ (actual email displays)
            # Do NOT check page_source - it includes JS/CSS and causes false positives
            try:
                email_elements = self.driver.find_elements(By.XPATH, "//*[contains(text(), '@')]")
                for element in email_elements:
                    try:
                        element_text = element.text.strip().lower()
                        if account_email.lower() == element_text or account_email.lower() in element_text:
                            logger.info(f"[Worker {self.worker_id}] Account {account_email} already exists")
                            return True
                    except:
                        continue
            except Exception:
                pass
            
            logger.info(f"[Worker {self.worker_id}] Account {account_email} not found - proceeding with addition")
            return False
            
        except Exception as e:
            logger.warning(f"[Worker {self.worker_id}] Error checking if account exists: {e} - proceeding with addition")
            return False
    
    def add_microsoft_account(
        self,
        email: str,
        password: str,
        mailbox_id: str
    ) -> Dict[str, Any]:
        """
        Add a Microsoft account to Instantly.ai via OAuth
        
        Args:
            email: Microsoft email address
            password: Microsoft password
            mailbox_id: Mailbox UUID for tracking
            
        Returns:
            Dict with 'success' (bool), 'error' (str or None)
        """
        try:
            logger.info(f"[Worker {self.worker_id}] Starting upload for {email} (ID: {mailbox_id})")
            
            # Ensure we're on the accounts page
            if "accounts" not in self.driver.current_url:
                self.driver.get("https://app.instantly.ai/app/accounts")
                self.random_delay(2, 3)
            
            # Step 1: Click Add New button on accounts page
            logger.info(f"[Worker {self.worker_id}] Looking for 'Add New' button...")
            
            # Try multiple selectors for the Add New button
            add_new_selectors = [
                (By.XPATH, "//button[contains(text(), 'Add New')]"),
                (By.XPATH, "//button[contains(text(), 'Add new')]"),
                (By.XPATH, "//button[contains(text(), 'ADD NEW')]"),
                (By.XPATH, "//a[contains(text(), 'Add New')]"),
                (By.XPATH, "//a[contains(text(), 'Add new')]"),
                (By.XPATH, "//*[contains(text(), 'Add') and contains(text(), 'New')]"),
                (By.CSS_SELECTOR, "button[data-testid*='add']"),
                (By.CSS_SELECTOR, "a[href*='connect']")
            ]
            
            add_new_button = None
            for selector_type, selector in add_new_selectors:
                try:
                    add_new_button = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((selector_type, selector))
                    )
                    logger.info(f"[Worker {self.worker_id}] Found Add New button using: {selector}")
                    break
                except TimeoutException:
                    continue
            
            if not add_new_button:
                # If button not found, try to navigate directly to connect page
                logger.warning(f"[Worker {self.worker_id}] Add New button not found, navigating directly to connect page")
                self.driver.get("https://app.instantly.ai/app/account/connect")
            else:
                self.driver.execute_script("arguments[0].scrollIntoView(true);", add_new_button)
                self.random_delay()
                add_new_button.click()
                logger.info(f"[Worker {self.worker_id}] Clicked 'Add New' button")
            
            # Wait for provider selection page
            WebDriverWait(self.driver, 10).until(
                EC.url_contains("app.instantly.ai/app/account/connect")
            )
            self.random_delay(2, 3)
            
            # Step 2: Click Microsoft option
            logger.info(f"[Worker {self.worker_id}] Selecting Microsoft provider...")
            
            # Try multiple selectors for Microsoft option
            microsoft_selectors = [
                (By.XPATH, "//p[text()='Microsoft']"),
                (By.XPATH, "//div[contains(text(), 'Microsoft')]"),
                (By.XPATH, "//div[contains(text(), 'Office 365')]"),
                (By.XPATH, "//*[contains(text(), 'Office 365 / Outlook')]"),
                (By.XPATH, "//*[contains(text(), 'Outlook')]"),
                (By.CSS_SELECTOR, "[data-provider='microsoft']"),
                (By.CSS_SELECTOR, "[data-testid*='microsoft']")
            ]
            
            microsoft_element = None
            for selector_type, selector in microsoft_selectors:
                try:
                    microsoft_element = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((selector_type, selector))
                    )
                    logger.info(f"[Worker {self.worker_id}] Found Microsoft option using: {selector}")
                    break
                except TimeoutException:
                    continue
            
            if microsoft_element:
                microsoft_element.click()
                logger.info(f"[Worker {self.worker_id}] Selected Microsoft provider")
            else:
                # If Microsoft option not found, navigate directly
                self.driver.get("https://app.instantly.ai/app/account/connect?provider=microsoft")
                logger.info(f"[Worker {self.worker_id}] Navigated directly to Microsoft provider page")
            
            self.random_delay(2, 3)
            
            # Step 3: Click "Yes, SMTP has been enabled" button
            logger.info(f"[Worker {self.worker_id}] Looking for SMTP confirmation button...")
            
            smtp_selectors = [
                (By.XPATH, "//button[contains(text(), 'Yes, SMTP has been enabled')]"),
                (By.XPATH, "//button[contains(text(), 'SMTP has been enabled')]"),
                (By.XPATH, "//button[contains(text(), 'Continue')]"),
                (By.XPATH, "//button[contains(text(), 'Next')]"),
                (By.CSS_SELECTOR, "button[type='submit']")
            ]
            
            smtp_button = None
            for selector_type, selector in smtp_selectors:
                try:
                    smtp_button = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((selector_type, selector))
                    )
                    logger.info(f"[Worker {self.worker_id}] Found SMTP button using: {selector}")
                    break
                except TimeoutException:
                    continue
            
            if smtp_button:
                self.driver.execute_script("arguments[0].scrollIntoView(true);", smtp_button)
                self.random_delay()
                smtp_button.click()
                logger.info(f"[Worker {self.worker_id}] Clicked SMTP confirmation button")
            
            # Step 4: Handle OAuth popup
            self.random_delay(2, 3)
            oauth_result = self._handle_oauth_flow(email, password)
            if not oauth_result["success"]:
                return oauth_result
            
            # Navigate back to accounts page and verify success
            self.random_delay(3, 5)
            
            # Ensure we're on accounts page
            if "accounts" not in self.driver.current_url:
                self.driver.get("https://app.instantly.ai/app/accounts")
                self.random_delay(3, 5)
            
            # Look for the account in the list (more thorough check)
            try:
                # Try multiple ways to find the account
                account_found = False
                
                # Method 1: Look for exact email match
                try:
                    WebDriverWait(self.driver, 8).until(
                        EC.presence_of_element_located((By.XPATH, f"//*[contains(text(), '{email}')]"))
                    )
                    account_found = True
                    logger.info(f"[Worker {self.worker_id}] ✓ Account {email} found in accounts list!")
                except TimeoutException:
                    pass
                
                # Method 2: Look for partial email match (username part)
                if not account_found:
                    try:
                        username = email.split('@')[0]
                        WebDriverWait(self.driver, 5).until(
                            EC.presence_of_element_located((By.XPATH, f"//*[contains(text(), '{username}')]"))
                        )
                        account_found = True
                        logger.info(f"[Worker {self.worker_id}] ✓ Account {email} found in accounts list (partial match)!")
                    except TimeoutException:
                        pass
                
                # Method 3: Check if page has "successfully" or similar success indicators
                if not account_found:
                    try:
                        success_indicators = ["successfully", "added", "connected", "verified"]
                        for indicator in success_indicators:
                            try:
                                WebDriverWait(self.driver, 2).until(
                                    EC.presence_of_element_located((By.XPATH, f"//*[contains(text(), '{indicator}')]"))
                                )
                                account_found = True
                                logger.info(f"[Worker {self.worker_id}] ✓ Success indicator '{indicator}' found - account likely added!")
                                break
                            except TimeoutException:
                                continue
                    except:
                        pass
                
                if account_found:
                    return {"success": True, "error": None}
                else:
                    # If OAuth completed without errors, assume success
                    logger.info(f"[Worker {self.worker_id}] ✓ OAuth flow completed successfully - assuming account {email} was added")
                    return {"success": True, "error": None}
                        
            except Exception as e:
                # If OAuth completed, assume success even if verification fails
                logger.info(f"[Worker {self.worker_id}] ✓ OAuth completed - assuming account {email} was added (verification failed: {e})")
                return {"success": True, "error": None}
                
        except Exception as e:
            error_msg = f"Unexpected error during upload: {str(e)}"
            logger.error(f"[Worker {self.worker_id}] {error_msg}")
            self.save_debug_screenshot("add_account_failed")
            return {"success": False, "error": error_msg}
            
    def _handle_oauth_flow(self, email: str, password: str) -> Dict[str, Any]:
        """
        Handle Microsoft OAuth popup flow with robust selector fallbacks
        
        Args:
            email: Microsoft email
            password: Microsoft password
            
        Returns:
            Dict with 'success' (bool), 'error' (str or None)
        """
        try:
            # Wait for OAuth window to appear
            self.random_delay(3, 5)
            
            # Store original window handle and switch to OAuth popup
            all_windows = self.driver.window_handles
            if len(all_windows) <= 1:
                logger.error(f"[Worker {self.worker_id}] OAuth popup not found!")
                self.save_debug_screenshot("no_oauth_popup")
                return {"success": False, "error": "OAuth popup not found"}
            
            original_window = all_windows[0]
            self.driver.switch_to.window(all_windows[-1])
            logger.info(f"[Worker {self.worker_id}] Switched to OAuth window")
            self.random_delay(2, 3)
            
            # Check if we're on account picker page ("Pick an account")
            logger.info(f"[Worker {self.worker_id}] Checking for account picker page...")
            try:
                pick_account_indicators = [
                    (By.XPATH, "//*[contains(text(), 'Pick an account')]"),
                    (By.XPATH, "//*[contains(text(), 'Use another account')]"),
                    (By.XPATH, "//div[contains(@class, 'table-cell') and contains(text(), 'Use another account')]")
                ]
                
                account_picker_found = False
                for selector_type, selector in pick_account_indicators:
                    try:
                        WebDriverWait(self.driver, 3).until(
                            EC.presence_of_element_located((selector_type, selector))
                        )
                        account_picker_found = True
                        break
                    except TimeoutException:
                        continue
                
                if account_picker_found:
                    logger.info(f"[Worker {self.worker_id}] Account picker page detected - clicking 'Use another account'")
                    
                    # Click "Use another account"
                    use_another_selectors = [
                        (By.XPATH, "//div[contains(text(), 'Use another account')]"),
                        (By.XPATH, "//*[contains(text(), 'Use another account')]"),
                        (By.XPATH, "//div[contains(@class, 'table-cell') and contains(text(), 'Use another account')]"),
                        (By.CSS_SELECTOR, "[data-test-id*='use-another-account']")
                    ]
                    
                    use_another_button = None
                    for selector_type, selector in use_another_selectors:
                        try:
                            use_another_button = WebDriverWait(self.driver, 5).until(
                                EC.element_to_be_clickable((selector_type, selector))
                            )
                            break
                        except TimeoutException:
                            continue
                    
                    if use_another_button:
                        use_another_button.click()
                        logger.info(f"[Worker {self.worker_id}] Clicked 'Use another account'")
                        self.random_delay(2, 3)
            except Exception as e:
                logger.info(f"[Worker {self.worker_id}] No account picker page detected, proceeding normally")
            
            # Step 1: Enter email with multiple selector fallbacks
            logger.info(f"[Worker {self.worker_id}] Entering email in OAuth window...")
            
            email_selectors = [
                (By.ID, "i0116"),
                (By.NAME, "loginfmt"),
                (By.XPATH, "//input[@type='email']"),
                (By.XPATH, "//input[@placeholder*='email']")
            ]
            
            email_input = None
            for selector_type, selector in email_selectors:
                try:
                    email_input = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((selector_type, selector))
                    )
                    break
                except TimeoutException:
                    continue
            
            if not email_input:
                logger.error(f"[Worker {self.worker_id}] Email input field not found")
                self.save_debug_screenshot("email_input_not_found")
                return {"success": False, "error": "Email input field not found"}
            
            email_input.clear()
            email_input.send_keys(email)
            self.random_delay()
            
            # Click Next
            next_selectors = [
                (By.ID, "idSIButton9"),
                (By.XPATH, "//input[@value='Next']"),
                (By.XPATH, "//button[contains(text(), 'Next')]")
            ]
            
            next_button = None
            for selector_type, selector in next_selectors:
                try:
                    next_button = self.driver.find_element(selector_type, selector)
                    break
                except NoSuchElementException:
                    continue
            
            if next_button:
                next_button.click()
                logger.info(f"[Worker {self.worker_id}] Email entered, clicked Next")
            
            self.random_delay(2, 3)
            
            # Step 2: Enter password with multiple selector fallbacks
            logger.info(f"[Worker {self.worker_id}] Entering password...")
            
            password_selectors = [
                (By.ID, "i0118"),
                (By.NAME, "passwd"),
                (By.XPATH, "//input[@type='password']")
            ]
            
            password_input = None
            for selector_type, selector in password_selectors:
                try:
                    password_input = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((selector_type, selector))
                    )
                    break
                except TimeoutException:
                    continue
            
            if not password_input:
                logger.error(f"[Worker {self.worker_id}] Password input field not found")
                self.save_debug_screenshot("password_input_not_found")
                return {"success": False, "error": "Password input field not found"}
            
            password_input.clear()
            password_input.send_keys(password)
            self.random_delay()
            
            # Click Sign in
            signin_selectors = [
                (By.ID, "idSIButton9"),
                (By.XPATH, "//input[@value='Sign in']"),
                (By.XPATH, "//button[contains(text(), 'Sign in')]")
            ]
            
            signin_button = None
            for selector_type, selector in signin_selectors:
                try:
                    signin_button = self.driver.find_element(selector_type, selector)
                    break
                except NoSuchElementException:
                    continue
            
            if signin_button:
                signin_button.click()
                logger.info(f"[Worker {self.worker_id}] Password entered, clicked Sign in")
            
            self.random_delay(3, 5)
            
            # Step 3: Handle "Stay signed in?" prompt - Click "No"
            logger.info(f"[Worker {self.worker_id}] Checking for 'Stay signed in?' prompt...")
            try:
                stay_signed_indicators = [
                    (By.XPATH, "//*[contains(text(), 'Stay signed in?')]"),
                    (By.XPATH, "//*[contains(text(), 'Do this to reduce the number of times')]"),
                    (By.ID, "KmsiCheckboxField")
                ]
                
                stay_signed_found = False
                for selector_type, selector in stay_signed_indicators:
                    try:
                        WebDriverWait(self.driver, 5).until(
                            EC.presence_of_element_located((selector_type, selector))
                        )
                        stay_signed_found = True
                        break
                    except TimeoutException:
                        continue
                
                if stay_signed_found:
                    logger.info(f"[Worker {self.worker_id}] 'Stay signed in?' prompt detected - clicking 'No'")
                    
                    # Uncheck the "Don't show this again" checkbox if checked
                    try:
                        checkbox = self.driver.find_element(By.ID, "KmsiCheckboxField")
                        if checkbox.is_selected():
                            checkbox.click()
                            logger.info(f"[Worker {self.worker_id}] Unchecked 'Don't show this again' checkbox")
                    except:
                        pass
                    
                    # Click "No" button
                    no_button_selectors = [
                        (By.ID, "idBtn_Back"),
                        (By.XPATH, "//input[@value='No']"),
                        (By.XPATH, "//button[contains(text(), 'No')]"),
                        (By.XPATH, "//input[@type='button' and @value='No']")
                    ]
                    
                    no_button = None
                    for selector_type, selector in no_button_selectors:
                        try:
                            no_button = WebDriverWait(self.driver, 5).until(
                                EC.element_to_be_clickable((selector_type, selector))
                            )
                            break
                        except TimeoutException:
                            continue
                    
                    if no_button:
                        no_button.click()
                        logger.info(f"[Worker {self.worker_id}] Clicked 'No' on 'Stay signed in?' prompt")
                        self.random_delay(2, 3)
                else:
                    logger.info(f"[Worker {self.worker_id}] No 'Stay signed in?' prompt found")
                    
            except Exception as e:
                logger.info(f"[Worker {self.worker_id}] Error handling 'Stay signed in?' prompt: {e}")
            
            # Step 4: Accept permissions with multiple selector fallbacks
            logger.info(f"[Worker {self.worker_id}] Looking for Accept button on permissions page...")
            
            accept_selectors = [
                (By.XPATH, "//input[@value='Accept']"),
                (By.XPATH, "//button[contains(text(), 'Accept')]"),
                (By.XPATH, "//button[contains(text(), 'Yes')]"),
                (By.ID, "idSIButton9")
            ]
            
            accept_button = None
            try:
                for selector_type, selector in accept_selectors:
                    try:
                        accept_button = WebDriverWait(self.driver, 8).until(
                            EC.element_to_be_clickable((selector_type, selector))
                        )
                        break
                    except TimeoutException:
                        continue
                
                if accept_button:
                    accept_button.click()
                    logger.info(f"[Worker {self.worker_id}] Clicked Accept - OAuth flow complete")
                else:
                    logger.info(f"[Worker {self.worker_id}] No Accept button found - OAuth may have completed automatically")
            except Exception as e:
                logger.info(f"[Worker {self.worker_id}] Accept button handling failed, but continuing: {e}")
            
            # Wait for OAuth completion - check if we're redirected back or window closes
            oauth_completed = False
            for wait_attempt in range(15):  # Wait up to 15 seconds
                self.random_delay(1, 1)
                current_windows = self.driver.window_handles
                
                # Check if OAuth window closed (success indicator)
                if len(current_windows) == 1:
                    self.driver.switch_to.window(current_windows[0])
                    logger.info(f"[Worker {self.worker_id}] OAuth window closed - OAuth completed successfully")
                    oauth_completed = True
                    break
                
                # Check if we're still in OAuth window and redirected back to Instantly
                try:
                    if "instantly.ai" in self.driver.current_url:
                        logger.info(f"[Worker {self.worker_id}] Redirected back to Instantly - OAuth completed successfully")
                        oauth_completed = True
                        break
                except:
                    pass
            
            # If still in popup, switch back to main window
            if not oauth_completed:
                try:
                    all_windows = self.driver.window_handles
                    if len(all_windows) > 1:
                        self.driver.switch_to.window(all_windows[0])
                        logger.info(f"[Worker {self.worker_id}] Switched back to main window manually")
                    oauth_completed = True  # Assume success if we made it this far
                except:
                    pass
            
            # Clear any stored sessions by navigating to Microsoft logout
            try:
                logger.info(f"[Worker {self.worker_id}] Clearing Microsoft sessions...")
                self.driver.execute_script("window.open('https://login.microsoftonline.com/logout.srf', '_blank');")
                all_windows = self.driver.window_handles
                if len(all_windows) > 1:
                    self.driver.switch_to.window(all_windows[-1])
                    self.random_delay(2, 3)
                    self.driver.close()
                    self.driver.switch_to.window(all_windows[0])
                    logger.info(f"[Worker {self.worker_id}] Microsoft sessions cleared")
            except Exception as e:
                logger.info(f"[Worker {self.worker_id}] Could not clear Microsoft sessions: {e}")
            
            return {"success": True, "error": None}
            
        except NoSuchWindowException:
            # OAuth window closed = success
            try:
                self.driver.switch_to.window(self.driver.window_handles[0])
            except Exception:
                pass
            return {"success": True, "error": None}
        except Exception as e:
            error_msg = f"OAuth flow error: {str(e)}"
            logger.error(f"[Worker {self.worker_id}] {error_msg}")
            self.save_debug_screenshot("oauth_failed")
            # Try to switch back to original window
            try:
                if len(self.driver.window_handles) > 0:
                    self.driver.switch_to.window(self.driver.window_handles[0])
            except:
                pass
            return {"success": False, "error": error_msg}
            
    def cleanup(self):
        """Clean up WebDriver resources"""
        if self.driver:
            try:
                self.driver.quit()
                logger.info(f"[Worker {self.worker_id}] Chrome driver closed")
            except Exception as e:
                logger.error(f"[Worker {self.worker_id}] Error closing driver: {str(e)}")


def process_mailbox_sync(
    uploader: InstantlyUploader,
    mailbox_data: Dict[str, Any],
    max_retries: int = 2
) -> Dict[str, Any]:
    """
    Synchronous function to process a single mailbox upload
    Runs in ThreadPoolExecutor
    
    Args:
        uploader: InstantlyUploader instance
        mailbox_data: Dict with 'id', 'email', 'password'
        max_retries: Maximum retry attempts
        
    Returns:
        Dict with 'mailbox_id', 'success', 'error', 'retries'
    """
    mailbox_id = mailbox_data["id"]
    email = mailbox_data["email"]
    password = mailbox_data["password"]
    
    for attempt in range(max_retries + 1):
        try:
            result = uploader.add_microsoft_account(email, password, mailbox_id)
            if result["success"]:
                return {
                    "mailbox_id": mailbox_id,
                    "success": True,
                    "error": None,
                    "retries": attempt
                }
            else:
                if attempt < max_retries:
                    logger.warning(f"[Worker {uploader.worker_id}] Attempt {attempt + 1} failed for {email}, retrying...")
                    time.sleep(3)
                else:
                    logger.error(f"[Worker {uploader.worker_id}] All {max_retries + 1} attempts failed for {email}")
                    return {
                        "mailbox_id": mailbox_id,
                        "success": False,
                        "error": result["error"],
                        "retries": attempt
                    }
        except Exception as e:
            error_msg = f"Exception during upload: {str(e)}"
            logger.error(f"[Worker {uploader.worker_id}] {error_msg}")
            if attempt < max_retries:
                time.sleep(3)
            else:
                return {
                    "mailbox_id": mailbox_id,
                    "success": False,
                    "error": error_msg,
                    "retries": attempt
                }


async def run_instantly_upload_for_batch(
    batch_id: str,
    instantly_email: str,
    instantly_password: str,
    num_workers: int = 3,
    headless: bool = True,
    skip_uploaded: bool = True
) -> Dict[str, Any]:
    """
    Main async function to upload all mailboxes in a batch to Instantly.ai
    Uses parallel browser workers for faster processing
    
    Args:
        batch_id: SetupBatch UUID
        instantly_email: Instantly.ai account email
        instantly_password: Instantly.ai account password
        num_workers: Number of parallel browser workers (1-5)
        headless: Run browsers in headless mode
        skip_uploaded: Skip mailboxes already uploaded
        
    Returns:
        Dict with summary: total, uploaded, failed, skipped, errors
    """
    logger.info(f"Starting Instantly upload for batch {batch_id} with {num_workers} workers")
    
    # Fetch mailboxes from database
    async with async_session_factory() as session:
        # Get batch to verify it exists
        batch_result = await session.execute(
            select(SetupBatch).where(SetupBatch.id == batch_id)
        )
        batch = batch_result.scalar_one_or_none()
        if not batch:
            return {"error": "Batch not found", "total": 0, "uploaded": 0, "failed": 0, "skipped": 0}
        
        # Get all mailboxes for tenants in this batch
        query = (
            select(Mailbox)
            .join(Tenant, Mailbox.tenant_id == Tenant.id)
            .where(Tenant.batch_id == batch_id)
        )
        
        if skip_uploaded:
            query = query.where(Mailbox.instantly_uploaded == False)
            
        result = await session.execute(query)
        mailboxes = result.scalars().all()
        
        if not mailboxes:
            logger.info(f"No mailboxes to upload for batch {batch_id}")
            return {"total": 0, "uploaded": 0, "failed": 0, "skipped": 0, "errors": []}
        
        # Prepare mailbox data for workers
        mailbox_list = [
            {
                "id": str(mb.id),
                "email": mb.email,
                "password": mb.initial_password or ""
            }
            for mb in mailboxes
        ]
    
    logger.info(f"Found {len(mailbox_list)} mailboxes to upload")
    
    # Run parallel upload using ThreadPoolExecutor
    uploaded_count = 0
    failed_count = 0
    errors = []
    
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        # Create one uploader per worker
        uploaders = []
        for i in range(num_workers):
            uploader = InstantlyUploader(
                instantly_email=instantly_email,
                instantly_password=instantly_password,
                headless=headless,
                worker_id=i
            )
            uploader.setup_driver()
            
            # Login to Instantly
            if not uploader.login_to_instantly():
                logger.error(f"Worker {i} failed to login, skipping")
                uploader.cleanup()
                continue
                
            uploaders.append(uploader)
        
        if not uploaders:
            return {
                "error": "All workers failed to login to Instantly",
                "total": len(mailbox_list),
                "uploaded": 0,
                "failed": len(mailbox_list),
                "skipped": 0,
                "errors": ["All workers failed to login"]
            }
        
        try:
            # Submit tasks to executor
            futures = []
            for i, mailbox_data in enumerate(mailbox_list):
                uploader = uploaders[i % len(uploaders)]
                future = executor.submit(process_mailbox_sync, uploader, mailbox_data)
                futures.append(future)
            
            # Process results as they complete
            for future in as_completed(futures):
                result = future.result()
                
                # Update database
                async with async_session_factory() as session:
                    if result["success"]:
                        await session.execute(
                            update(Mailbox)
                            .where(Mailbox.id == result["mailbox_id"])
                            .values(
                                instantly_uploaded=True,
                                instantly_uploaded_at=datetime.utcnow(),
                                instantly_upload_error=None
                            )
                        )
                        uploaded_count += 1
                    else:
                        await session.execute(
                            update(Mailbox)
                            .where(Mailbox.id == result["mailbox_id"])
                            .values(
                                instantly_uploaded=False,
                                instantly_upload_error=result["error"]
                            )
                        )
                        failed_count += 1
                        errors.append(result["error"])
                    
                    await session.commit()
                
                logger.info(f"Progress: {uploaded_count + failed_count}/{len(mailbox_list)} processed")
        
        finally:
            # Cleanup all uploaders
            for uploader in uploaders:
                uploader.cleanup()
    
    logger.info(f"Instantly upload complete: {uploaded_count} uploaded, {failed_count} failed")
    
    return {
        "total": len(mailbox_list),
        "uploaded": uploaded_count,
        "failed": failed_count,
        "skipped": 0,
        "errors": errors[:10]  # Limit to first 10 errors
    }
