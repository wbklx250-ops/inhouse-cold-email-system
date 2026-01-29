"""
Microsoft Login Automation with Complete State Detection

Handles all possible login states:
- Email entry
- Password entry
- Mandatory password change
- MFA enrollment (extracts TOTP secret)
- MFA code entry (uses existing TOTP)
- "Stay signed in?" prompt
- Security Defaults disable
- Already logged in
- Error states
"""

import re
import time
import logging
from enum import Enum
from typing import Optional, Tuple
from dataclasses import dataclass

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

import pyotp

from .browser import create_driver, take_screenshot, cleanup_driver
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class LoginState(Enum):
    """All possible states during Microsoft login."""
    UNKNOWN = "unknown"
    NEEDS_EMAIL = "needs_email"
    NEEDS_PASSWORD = "needs_password"
    NEEDS_PASSWORD_CHANGE = "needs_password_change"
    NEEDS_MFA_SETUP = "needs_mfa_setup"
    NEEDS_MFA_METHOD_SELECT = "needs_mfa_method_select"
    NEEDS_MFA_CODE = "needs_mfa_code"
    NEEDS_STAY_SIGNED_IN = "needs_stay_signed_in"
    LOGGED_IN = "logged_in"
    ERROR = "error"


@dataclass
class FirstLoginResult:
    """Result of first login automation."""
    success: bool
    new_password: Optional[str] = None
    totp_secret: Optional[str] = None
    security_defaults_disabled: bool = False
    error: Optional[str] = None
    screenshots: list = None
    
    def __post_init__(self):
        if self.screenshots is None:
            self.screenshots = []


class MicrosoftLoginAutomation:
    """Automates Microsoft tenant first login."""
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.driver: Optional[webdriver.Chrome] = None
        self.screenshots: list = []
        settings = get_settings()
        self._headless_delay_seconds = settings.headless_delay_seconds
        self._headless_page_settle_seconds = settings.headless_page_settle_seconds

    def _settle_after_action(self, base_delay: float = 0.5, extra_delay: float = 0.0) -> None:
        """Allow the page to settle after an action; slower when headless."""
        delay = base_delay
        if self.headless:
            delay = max(delay, self._headless_delay_seconds)
            delay += extra_delay
        time.sleep(delay)
    
    def _screenshot(self, name: str) -> str:
        """Take screenshot and track it."""
        path = take_screenshot(self.driver, name)
        if path:
            self.screenshots.append(path)
        return path
    
    def _find_element(self, selectors: list, timeout: int = 5):
        """Try multiple selectors, return first match."""
        for by, value in selectors:
            try:
                return WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located((by, value))
                )
            except TimeoutException:
                continue
        return None
    
    def _click_if_exists(self, selectors: list, timeout: int = 3) -> bool:
        """Click element if it exists."""
        elem = self._find_element(selectors, timeout)
        if elem:
            try:
                elem.click()
                return True
            except:
                pass
        return False
    
    def _click_next_button(self, timeout: int = 5) -> bool:
        """Click Next button - handles different Microsoft page variations."""
        return self._click_if_exists([
            # New Microsoft UI (reskin) - data-testid
            (By.CSS_SELECTOR, "button[data-testid='reskin-step-next-button']"),
            
            # Old Microsoft UI - id based
            (By.ID, "idSubmit_ProofUp_Redirect"),
            (By.ID, "idSIButton9"),
            
            # Text-based fallbacks
            (By.XPATH, "//button[normalize-space()='Next']"),
            (By.XPATH, "//button[contains(text(), 'Next')]"),
            
            # Input submit buttons
            (By.CSS_SELECTOR, "input[type='submit'][value='Next']"),
        ], timeout=timeout)
    
    def detect_state(self) -> LoginState:
        """Detect current page state."""
        # Wait for page to be ready before detecting state
        try:
            WebDriverWait(self.driver, 5).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            self._settle_after_action(base_delay=0.5, extra_delay=self._headless_page_settle_seconds)
        except:
            pass
        
        url = self.driver.current_url.lower()
        page = self.driver.page_source.lower()
        
        logger.debug(f"[STATE] URL: {url[:100]}...")
        
        # Error states
        if "error" in url or "something went wrong" in page:
            return LoginState.ERROR
        
        # Logged in states
        if "portal.azure.com" in url and ("#home" in url or "#blade" in url):
            return LoginState.LOGGED_IN
        if "myapplications" in url or "myapps.microsoft.com" in url:
            return LoginState.LOGGED_IN
        if "office.com" in url and "landing" in url:
            return LoginState.LOGGED_IN
        
        # Stay signed in
        if "kmsi" in url or "stay signed in" in page:
            return LoginState.NEEDS_STAY_SIGNED_IN
        
        # Password change
        if "passwordchange" in url or "update your password" in page:
            return LoginState.NEEDS_PASSWORD_CHANGE
        
        # MFA Setup / Security Defaults "Action Required" prompt
        # This catches the SSPR/End page with "Security defaults are enabled"
        if "sspr" in url or "action required" in page:
            if "security defaults" in page or "multifactor authentication" in page:
                logger.info("[STATE] Detected MFA setup / Security Defaults page")
                return LoginState.NEEDS_MFA_SETUP
        
        # MFA setup - expanded detection
        if "more information required" in page or "keep your account secure" in page:
            if "authenticator" in page:
                return LoginState.NEEDS_MFA_METHOD_SELECT
            return LoginState.NEEDS_MFA_SETUP
        
        # MFA code entry
        if self._find_element([
            (By.CSS_SELECTOR, "input[name='otc']"),
            (By.CSS_SELECTOR, "input[type='tel'][maxlength='6']"),
        ], timeout=2):
            return LoginState.NEEDS_MFA_CODE
        
        # Email entry
        if self._find_element([
            (By.NAME, "loginfmt"),
            (By.CSS_SELECTOR, "input[type='email']"),
        ], timeout=2):
            return LoginState.NEEDS_EMAIL
        
        # Password entry
        if self._find_element([
            (By.NAME, "passwd"),
            (By.CSS_SELECTOR, "input[type='password']"),
        ], timeout=2):
            return LoginState.NEEDS_PASSWORD
        
        return LoginState.UNKNOWN
    
    def handle_email(self, email: str) -> bool:
        """Enter email and submit."""
        logger.info(f"Entering email: {email}")
        
        email_input = self._find_element([
            (By.NAME, "loginfmt"),
            (By.ID, "i0116"),
        ], timeout=30)
        
        if not email_input:
            return False
        
        email_input.clear()
        self._settle_after_action(base_delay=0.2)
        email_input.send_keys(email)
        self._settle_after_action(base_delay=0.3)
        email_input.send_keys(Keys.RETURN)
        
        # Wait for page to transition
        try:
            WebDriverWait(self.driver, 30).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except:
            pass
        self._settle_after_action(base_delay=0.5, extra_delay=self._headless_page_settle_seconds)
        return True
    
    def handle_password(self, password: str) -> bool:
        """Enter password and submit."""
        logger.info("Entering password")
        
        pwd_input = self._find_element([
            (By.NAME, "passwd"),
            (By.ID, "i0118"),
        ], timeout=30)
        
        if not pwd_input:
            return False
        
        pwd_input.clear()
        self._settle_after_action(base_delay=0.2)
        pwd_input.send_keys(password)
        self._settle_after_action(base_delay=0.3)
        pwd_input.send_keys(Keys.RETURN)
        
        # Wait for page to transition
        try:
            WebDriverWait(self.driver, 30).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except:
            pass
        self._settle_after_action(base_delay=0.5, extra_delay=self._headless_page_settle_seconds)
        return True
    
    def handle_password_change(self, current: str, new: str) -> bool:
        """Handle forced password change."""
        logger.info("Handling password change")
        self._screenshot("password_change")
        
        # Current password
        curr_input = self._find_element([
            (By.NAME, "oldPassword"),
            (By.NAME, "currentPassword"),
            (By.ID, "currentPassword"),
        ], timeout=30)
        if curr_input:
            curr_input.clear()
            self._settle_after_action(base_delay=0.2)
            curr_input.send_keys(current)
        
        # New password
        new_input = self._find_element([
            (By.NAME, "newPassword"),
            (By.ID, "newPassword"),
        ], timeout=30)
        if new_input:
            new_input.clear()
            self._settle_after_action(base_delay=0.2)
            new_input.send_keys(new)
        
        # Confirm password
        confirm_input = self._find_element([
            (By.NAME, "confirmPassword"),
            (By.NAME, "reenterPassword"),
        ], timeout=30)
        if confirm_input:
            confirm_input.clear()
            self._settle_after_action(base_delay=0.2)
            confirm_input.send_keys(new)
            self._settle_after_action(base_delay=0.3)
            confirm_input.send_keys(Keys.RETURN)
        else:
            self._click_if_exists([
                (By.CSS_SELECTOR, "input[type='submit']"),
                (By.CSS_SELECTOR, "button[type='submit']"),
            ])
        
        # Wait for page to transition
        try:
            WebDriverWait(self.driver, 30).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except:
            pass
        self._settle_after_action(base_delay=0.5, extra_delay=self._headless_page_settle_seconds)
        return True
    
    def extract_totp_only(self) -> Optional[str]:
        """
        Phase 1: Navigate to secret page and extract TOTP secret.
        Does NOT complete enrollment (no code entry / verify / done clicks).
        """
        worker_id = getattr(self, 'worker_id', 0)
        
        logger.info(f"[W{worker_id}] ======= MFA SETUP START =======")
        logger.info(f"[W{worker_id}] Current URL: {self.driver.current_url}")
        logger.info(f"[W{worker_id}] Page title: {self.driver.title}")
        
        try:
            page_text = self.driver.find_element(By.TAG_NAME, "body").text
            logger.info(f"[W{worker_id}] Page text (first 500 chars): {page_text[:500]}")
        except Exception as e:
            logger.error(f"[W{worker_id}] Could not get page text: {e}")
        
        # Log ALL buttons on the page
        try:
            buttons = self.driver.find_elements(By.TAG_NAME, "button")
            logger.info(f"[W{worker_id}] Found {len(buttons)} buttons:")
            for i, btn in enumerate(buttons):
                try:
                    btn_text = btn.text.strip()
                    btn_id = btn.get_attribute('id') or ''
                    btn_type = btn.get_attribute('type') or ''
                    btn_visible = btn.is_displayed()
                    btn_enabled = btn.is_enabled()
                    logger.info(f"[W{worker_id}]   Button {i}: text='{btn_text}' id='{btn_id}' type='{btn_type}' visible={btn_visible} enabled={btn_enabled}")
                except Exception as e:
                    logger.info(f"[W{worker_id}]   Button {i}: ERROR getting info - {e}")
        except Exception as e:
            logger.error(f"[W{worker_id}] Could not enumerate buttons: {e}")
        
        # Also log input elements (some Next buttons are inputs)
        try:
            inputs = self.driver.find_elements(By.TAG_NAME, "input")
            submit_inputs = [inp for inp in inputs if inp.get_attribute('type') in ('submit', 'button')]
            logger.info(f"[W{worker_id}] Found {len(submit_inputs)} submit/button inputs:")
            for i, inp in enumerate(submit_inputs):
                try:
                    inp_value = inp.get_attribute('value') or ''
                    inp_id = inp.get_attribute('id') or ''
                    inp_type = inp.get_attribute('type') or ''
                    inp_visible = inp.is_displayed()
                    inp_enabled = inp.is_enabled()
                    logger.info(f"[W{worker_id}]   Input {i}: value='{inp_value}' id='{inp_id}' type='{inp_type}' visible={inp_visible} enabled={inp_enabled}")
                except Exception as e:
                    logger.info(f"[W{worker_id}]   Input {i}: ERROR getting info - {e}")
        except Exception as e:
            logger.error(f"[W{worker_id}] Could not enumerate inputs: {e}")
        
        self._screenshot("mfa_setup_start")
        
        # STEP 1: Click first Next (Action Required / Security Defaults page)
        logger.info(f"[W{worker_id}] --- Step 1: Click first Next (Action Required page) ---")
        self._click_next_button()
        # Wait for page to transition
        try:
            WebDriverWait(self.driver, 30).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            self._settle_after_action(base_delay=0.5, extra_delay=self._headless_page_settle_seconds)
        except:
            pass
        self._screenshot("mfa_after_first_next")
        
        # STEP 2: Detect "Install Microsoft Authenticator" page and click "different app" BEFORE Next
        logger.info(f"[W{worker_id}] --- Step 2: Check for 'Install Microsoft Authenticator' page ---")
        try:
            page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            logger.info(f"[W{worker_id}] Page text (first 300 chars): {page_text[:300]}")
        except Exception as e:
            page_text = ""
            logger.error(f"[W{worker_id}] Could not get page text: {e}")
        
        # Check if on "Install Microsoft Authenticator" page
        if "install microsoft authenticator" in page_text or "get it on google play" in page_text or "get the app" in page_text:
            logger.info(f"[W{worker_id}] DETECTED: 'Install Microsoft Authenticator' page - clicking 'different app' BUTTON FIRST!")
            
            # CRITICAL: It's a BUTTON, NOT A LINK! By.PARTIAL_LINK_TEXT only works for <a> tags!
            diff_app_clicked = self._click_if_exists([
                # BUTTON selectors - Microsoft uses a button styled as a link!
                (By.XPATH, "//button[contains(text(), 'Set up a different authentication app')]"),
                (By.XPATH, "//button[contains(text(), 'different authentication')]"),
                (By.XPATH, "//button[contains(., 'different authentication')]"),
                (By.CSS_SELECTOR, "button.ms-Link"),
                # Wildcard as fallback
                (By.XPATH, "//*[contains(text(), 'I want to use a different')]"),
            ], timeout=5)
            logger.info(f"[W{worker_id}] 'Set up a different authentication app' BUTTON clicked: {diff_app_clicked}")
            
            if not diff_app_clicked:
                logger.error(f"[W{worker_id}] FAILED to click 'different authentication app' button! Listing all buttons:")
                try:
                    buttons = self.driver.find_elements(By.TAG_NAME, "button")
                    for i, btn in enumerate(buttons):
                        logger.error(f"[W{worker_id}]   BUTTON {i}: text='{btn.text}'")
                except Exception as e:
                    logger.error(f"[W{worker_id}]   Error listing buttons: {e}")
            # Wait for page to transition
            try:
                WebDriverWait(self.driver, 30).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
                self._settle_after_action(base_delay=0.5, extra_delay=self._headless_page_settle_seconds)
            except:
                pass
            self._screenshot("mfa_after_different_app_click")
        else:
            logger.info(f"[W{worker_id}] Not on 'Install Microsoft Authenticator' page, continuing...")
        
        # STEP 3: Click Next to proceed (now we should be in TOTP flow)
        logger.info(f"[W{worker_id}] --- Step 3: Click Next to proceed to QR/secret page ---")
        self._click_next_button()
        # Wait for page to transition
        try:
            WebDriverWait(self.driver, 30).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            self._settle_after_action(base_delay=0.5, extra_delay=self._headless_page_settle_seconds)
        except:
            pass
        self._screenshot("mfa_after_second_next")
        
        # STEP 4: Handle any additional pages (some flows have more steps)
        logger.info(f"[W{worker_id}] --- Step 4: Handle any additional setup pages ---")
        for i in range(3):
            try:
                page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            except:
                page_text = ""
            
            # If we see "scan this qr code" or "secret key", we're in the right place
            if "scan" in page_text or "secret" in page_text or "qr code" in page_text:
                logger.info(f"[W{worker_id}] Found QR/secret page, breaking loop")
                break
            
            # Try clicking Next if available
            if self._click_next_button(timeout=2):
                logger.info(f"[W{worker_id}] Clicked additional Next button (iteration {i})")
                # Wait for page to transition
                try:
                    WebDriverWait(self.driver, 30).until(
                        lambda d: d.execute_script("return document.readyState") == "complete"
                    )
                    self._settle_after_action(base_delay=0.5, extra_delay=self._headless_page_settle_seconds)
                except:
                    pass
            else:
                logger.info(f"[W{worker_id}] No more Next buttons, breaking loop")
                break
        
        self._screenshot("mfa_qr_page")
        
        logger.info(f"[W{worker_id}] --- Looking for 'Can't scan?' BUTTON ---")
        # Click "Can't scan?" to reveal secret - IT'S A BUTTON, NOT A LINK!
        cant_scan_clicked = self._click_if_exists([
            # BUTTON selectors - Microsoft uses a button styled as a link!
            (By.CSS_SELECTOR, "button[data-testid='activation-qr-show/hide-info-button']"),
            (By.CSS_SELECTOR, "button.ms-Link"),
            (By.XPATH, "//button[contains(text(), \"Can't scan\")]"),
            (By.XPATH, "//button[contains(., 'scan')]"),
            # Wildcard fallback
            (By.XPATH, "//*[contains(text(), \"Can't scan\")]"),
            (By.XPATH, "//*[contains(text(), 'manually')]"),
        ])
        logger.info(f"[W{worker_id}] 'Can't scan?' BUTTON clicked: {cant_scan_clicked}")

        if not cant_scan_clicked:
            logger.error(f"[W{worker_id}] FAILED to click 'Can't scan' button")
            self._screenshot("mfa_ERROR_cant_scan")
            return None

        # Wait for secret to be revealed
        try:
            WebDriverWait(self.driver, 30).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            self._settle_after_action(base_delay=0.5, extra_delay=self._headless_page_settle_seconds)
        except:
            pass
        self._screenshot("mfa_secret_page")
        # Extract TOTP secret
        logger.info(f"[W{worker_id}] --- Extracting TOTP secret ---")
        totp_secret = self._extract_totp_secret()

        if totp_secret:
            logger.info(f"[W{worker_id}]  Extracted TOTP: {totp_secret[:4]}...")
            return totp_secret

        logger.error(f"[W{worker_id}]  Could not extract TOTP secret from page!")
        logger.info(f"[W{worker_id}] Current URL: {self.driver.current_url}")
        try:
            page_text = self.driver.find_element(By.TAG_NAME, "body").text
            logger.info(f"[W{worker_id}] Page text at failure: {page_text[:1000]}")
        except:
            pass
        self._screenshot("mfa_ERROR_no_secret")
        
        logger.info(f"[W{worker_id}] ======= MFA SETUP FAILED (NO SECRET) =======")
        return None

    def complete_mfa_enrollment(self, totp_secret: str) -> bool:
        """
        Phase 2: Complete MFA enrollment by entering code and finishing steps.
        MUST ONLY be called after TOTP is saved to DB.
        """
        worker_id = getattr(self, 'worker_id', 0)

        logger.info(f"[W{worker_id}] --- Clicking Next to go to code entry ---")
        next_to_code = self._click_next_button()
        logger.info(f"[W{worker_id}] Next to code entry clicked: {next_to_code}")
        # Wait for code entry page
        try:
            WebDriverWait(self.driver, 30).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            self._settle_after_action(base_delay=0.5, extra_delay=self._headless_page_settle_seconds)
        except:
            pass

        code = pyotp.TOTP(totp_secret).now()
        logger.info(f"[W{worker_id}] Generated MFA code: {code}")

        code_input = self._find_element([
            (By.CSS_SELECTOR, "input[name='otc']"),
            (By.CSS_SELECTOR, "input[type='tel']"),
            (By.CSS_SELECTOR, "input[maxlength='6']"),
        ])

        if not code_input:
            logger.error(f"[W{worker_id}]  Could not find code input field!")
            self._screenshot("mfa_ERROR_no_code_input")
            return False

        logger.info(f"[W{worker_id}] Found code input field")
        code_input.clear()
        self._settle_after_action(base_delay=0.2)
        code_input.send_keys(code)
        logger.info(f"[W{worker_id}]  Entered code: {code}")
        self._settle_after_action(base_delay=0.3)

        logger.info(f"[W{worker_id}] --- Clicking Verify/Next ---")
        verify_clicked = self._click_if_exists([
            (By.XPATH, "//button[contains(text(), 'Verify')]"),
            # New Microsoft UI (reskin) - data-testid
            (By.CSS_SELECTOR, "button[data-testid='reskin-step-next-button']"),
            # Old Microsoft UI - id based
            (By.ID, "idSubmit_ProofUp_Redirect"),
            (By.ID, "idSIButton9"),
            # Text-based fallbacks
            (By.XPATH, "//button[normalize-space()='Next']"),
            (By.XPATH, "//button[contains(text(), 'Next')]"),
        ])
        logger.info(f"[W{worker_id}] Verify/Next clicked: {verify_clicked}")
        # Wait for verification to process
        try:
            WebDriverWait(self.driver, 30).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            self._settle_after_action(base_delay=0.5, extra_delay=self._headless_page_settle_seconds)
        except:
            pass
        logger.info(f"[W{worker_id}] After verify URL: {self.driver.current_url}")
        self._screenshot("mfa_after_verify")

        logger.info(f"[W{worker_id}] --- Clicking completion buttons ---")
        for i in range(5):
            done_clicked = self._click_if_exists([
                (By.XPATH, "//button[contains(text(), 'Done')]"),
                (By.XPATH, "//button[contains(text(), 'Finish')]"),
                (By.XPATH, "//button[contains(text(), 'OK')]"),
                (By.ID, "idSIButton9"),
            ])
            if done_clicked:
                logger.info(f"[W{worker_id}]  Clicked completion button (iteration {i})")
                # Wait for page to transition
                try:
                    WebDriverWait(self.driver, 30).until(
                        lambda d: d.execute_script("return document.readyState") == "complete"
                    )
                    self._settle_after_action(base_delay=0.5, extra_delay=self._headless_page_settle_seconds)
                except:
                    pass

        logger.info(f"[W{worker_id}] ======= MFA SETUP COMPLETE =======")
        logger.info(f"[W{worker_id}] Final URL: {self.driver.current_url}")
        self._screenshot("mfa_complete")
        return True
    
    def _extract_totp_secret(self) -> Optional[str]:
        """Extract TOTP secret from page."""
        page = self.driver.page_source
        
        # Look for secret in otpauth URL
        match = re.search(r'secret=([A-Z2-7]{16,64})', page, re.IGNORECASE)
        if match:
            return match.group(1).upper()
        
        # Look for base32 secret on page
        matches = re.findall(r'\b([A-Z2-7]{16,64})\b', page)
        for m in matches:
            try:
                pyotp.TOTP(m).now()  # Validate it's valid base32
                return m
            except:
                continue
        
        return None
    
    def handle_mfa_code(self, totp_secret: str) -> bool:
        """Enter MFA code using stored TOTP secret."""
        logger.info("Entering MFA code")
        
        code = pyotp.TOTP(totp_secret).now()
        
        code_input = self._find_element([
            (By.CSS_SELECTOR, "input[name='otc']"),
            (By.CSS_SELECTOR, "input[type='tel']"),
        ], timeout=30)
        
        if code_input:
            code_input.clear()
            self._settle_after_action(base_delay=0.2)
            code_input.send_keys(code)
            self._settle_after_action(base_delay=0.3)
            
            self._click_if_exists([
                (By.XPATH, "//button[contains(text(), 'Verify')]"),
                (By.XPATH, "//button[contains(text(), 'Sign in')]"),
                (By.CSS_SELECTOR, "input[type='submit']"),
            ])
            # Wait for verification
            try:
                WebDriverWait(self.driver, 30).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
                self._settle_after_action(base_delay=0.5, extra_delay=self._headless_page_settle_seconds)
            except:
                pass
            return True
        
        return False
    
    def handle_stay_signed_in(self) -> bool:
        """Handle 'Stay signed in?' prompt."""
        logger.info("Handling stay signed in")
        
        self._click_if_exists([
            (By.ID, "idBtn_Back"),  # "No" button
            (By.XPATH, "//button[contains(text(), 'No')]"),
        ])
        # Wait for page to transition
        try:
            WebDriverWait(self.driver, 30).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            self._settle_after_action(base_delay=0.5, extra_delay=self._headless_page_settle_seconds)
        except:
            pass
        return True
    
    def disable_security_defaults(self) -> bool:
        """Navigate to Entra ID and disable Security Defaults."""
        logger.info("Disabling Security Defaults")
        
        try:
            self.driver.get("https://entra.microsoft.com/#view/Microsoft_AAD_IAM/SecurityDefaultsBlade")
            # Wait for page to fully load
            try:
                WebDriverWait(self.driver, 30).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
                self._settle_after_action(base_delay=0.5, extra_delay=self._headless_page_settle_seconds)
            except:
                pass
            
            self._screenshot("security_defaults_page")
            
            page = self.driver.page_source.lower()
            
            # Check if already disabled
            if "security defaults is disabled" in page:
                logger.info("Security Defaults already disabled")
                return True
            
            # Click Disabled option
            self._click_if_exists([
                (By.XPATH, "//label[contains(., 'Disabled')]"),
                (By.XPATH, "//span[text()='Disabled']/ancestor::div[@role='radio']"),
            ], timeout=30)
            
            # Select reason
            self._click_if_exists([
                (By.XPATH, "//option[contains(., 'Other')]"),
            ], timeout=30)
            
            # Save
            self._click_if_exists([
                (By.XPATH, "//button[contains(., 'Save')]"),
                (By.CSS_SELECTOR, "button[type='submit']"),
            ], timeout=30)
            
            # Wait for save to complete
            try:
                WebDriverWait(self.driver, 30).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
                self._settle_after_action(base_delay=0.5, extra_delay=self._headless_page_settle_seconds)
            except:
                pass
            self._screenshot("security_defaults_saved")
            return True
            
        except Exception as e:
            logger.error(f"Failed to disable Security Defaults: {e}")
            self._screenshot("security_defaults_error")
            return False
    
    async def complete_first_login(
        self,
        admin_email: str,
        initial_password: str,
        new_password: str,
        existing_totp: Optional[str] = None
    ) -> FirstLoginResult:
        """
        Complete the entire first login flow.
        
        Returns FirstLoginResult with credentials and status.
        """
        result = FirstLoginResult(success=False)
        
        try:
            self.driver = create_driver(self.headless)
            self.driver.get("https://portal.azure.com")
            # Wait for initial page load
            try:
                WebDriverWait(self.driver, 30).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
                self._settle_after_action(base_delay=0.5, extra_delay=self._headless_page_settle_seconds)
            except:
                pass
            
            totp_secret = existing_totp
            current_password = initial_password
            
            for iteration in range(20):
                state = self.detect_state()
                logger.info(f"Iteration {iteration}: State = {state.value}")
                self._screenshot(f"state_{iteration}_{state.value}")
                
                if state == LoginState.LOGGED_IN:
                    break
                elif state == LoginState.ERROR:
                    result.error = "Login error detected"
                    return result
                elif state == LoginState.NEEDS_EMAIL:
                    self.handle_email(admin_email)
                elif state == LoginState.NEEDS_PASSWORD:
                    self.handle_password(current_password)
                elif state == LoginState.NEEDS_PASSWORD_CHANGE:
                    self.handle_password_change(current_password, new_password)
                    current_password = new_password
                    result.new_password = new_password
                elif state in (LoginState.NEEDS_MFA_SETUP, LoginState.NEEDS_MFA_METHOD_SELECT):
                    extracted = self.extract_totp_only()
                    if extracted:
                        totp_secret = extracted
                        result.totp_secret = totp_secret
                elif state == LoginState.NEEDS_MFA_CODE:
                    if totp_secret:
                        self.handle_mfa_code(totp_secret)
                    else:
                        result.error = "MFA code required but no TOTP secret"
                        return result
                elif state == LoginState.NEEDS_STAY_SIGNED_IN:
                    self.handle_stay_signed_in()
                elif state == LoginState.UNKNOWN:
                    # Wait a bit for page to stabilize
                    try:
                        WebDriverWait(self.driver, 5).until(
                            lambda d: d.execute_script("return document.readyState") == "complete"
                        )
                        self._settle_after_action(base_delay=0.5, extra_delay=self._headless_page_settle_seconds)
                    except:
                        pass
                
                # Brief pause between state checks
                self._settle_after_action(base_delay=0.5)
            
            # Final check
            if self.detect_state() == LoginState.LOGGED_IN:
                # Disable Security Defaults
                if self.disable_security_defaults():
                    result.security_defaults_disabled = True
                
                result.success = True
                result.new_password = result.new_password or initial_password
                result.totp_secret = totp_secret
            else:
                result.error = "Did not reach logged in state"
            
        except Exception as e:
            logger.exception(f"First login failed: {e}")
            result.error = str(e)
            self._screenshot("exception")
        
        finally:
            result.screenshots = self.screenshots
            if self.driver:
                cleanup_driver(self.driver)
                self.driver = None
        
        return result