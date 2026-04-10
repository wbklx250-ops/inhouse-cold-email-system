"""
Shared Selenium flow: Microsoft OAuth sign-in for sequencer inbox connect URLs.

Used by Smartlead, PlusVibe, and any similar product that hands you a custom
OAuth URL and completes in a vendor-controlled redirect.
"""

from __future__ import annotations

import logging
import os
import random
import time
from datetime import datetime
from typing import Sequence, Tuple

logger = logging.getLogger(__name__)


class MicrosoftSequencerOAuthUploader:
    """
    Uploads one M365 account by opening the sequencer's OAuth URL and driving
    the Microsoft login + consent UI. Subclasses / callers set URL markers used
    only for logging (success is still True if all steps complete without error).
    """

    def __init__(
        self,
        headless: bool = True,
        worker_id: int = 0,
        *,
        success_url_markers: Sequence[str] = ("smartlead",),
        screenshot_prefix: str = "ms_oauth",
    ):
        self.headless = headless
        self.worker_id = worker_id
        self.success_url_markers: Tuple[str, ...] = tuple(
            m.lower() for m in success_url_markers if m
        )
        self.screenshot_prefix = screenshot_prefix

    def upload_account(self, email: str, password: str, oauth_url: str) -> bool:
        """Upload a single M365 account via OAuth. Returns True on success."""
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait

        driver = None
        try:
            chrome_options = webdriver.ChromeOptions()
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option("useAutomationExtension", False)

            if self.headless:
                chrome_options.add_argument("--headless=new")

            driver = webdriver.Chrome(options=chrome_options)
            driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            driver.set_page_load_timeout(25)
            wait = WebDriverWait(driver, 12)

            logger.info(f"[Worker {self.worker_id}] Starting OAuth for {email}")
            driver.get(oauth_url)
            time.sleep(3 + random.uniform(0, 1))

            email_field = self._find_element(
                wait, [(By.NAME, "loginfmt"), (By.ID, "i0116")]
            )
            if not email_field:
                self._screenshot(driver, f"no_email_{email.split('@')[0]}")
                raise Exception("Email field not found")

            self._human_type(email_field, email)
            time.sleep(0.5)

            next_btn = self._find_element(
                wait, [(By.CSS_SELECTOR, 'input[type="submit"]'), (By.ID, "idSIButton9")]
            )
            if next_btn:
                self._safe_click(driver, next_btn)
            time.sleep(3 + random.uniform(0, 1))

            pass_field = self._find_element(
                wait, [(By.NAME, "passwd"), (By.ID, "i0118")]
            )
            if not pass_field:
                self._screenshot(driver, f"no_pass_{email.split('@')[0]}")
                raise Exception("Password field not found")

            self._human_type(pass_field, password)
            time.sleep(0.5)

            signin_btn = self._find_element(
                wait, [(By.CSS_SELECTOR, 'input[type="submit"]'), (By.ID, "idSIButton9")]
            )
            if signin_btn:
                self._safe_click(driver, signin_btn)
            time.sleep(4 + random.uniform(0, 1))

            self._handle_post_login(driver)
            self._handle_consent(driver)

            time.sleep(3)
            cur = driver.current_url.lower()
            if self.success_url_markers and any(m in cur for m in self.success_url_markers):
                logger.info(f"[Worker {self.worker_id}] OAuth success for {email}")
                return True
            logger.warning(f"[Worker {self.worker_id}] Unclear result for {email}, URL: {driver.current_url}")
            self._screenshot(driver, f"unclear_{email.split('@')[0]}")
            return True

        except Exception as e:
            logger.error(f"[Worker {self.worker_id}] OAuth failed for {email}: {e}")
            if driver:
                self._screenshot(driver, f"error_{email.split('@')[0]}")
            return False

        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    def _find_element(self, wait, locators):
        from selenium.common.exceptions import TimeoutException
        from selenium.webdriver.support import expected_conditions as EC

        for locator in locators:
            try:
                el = wait.until(EC.visibility_of_element_located(locator))
                return el
            except TimeoutException:
                continue
        return None

    def _safe_click(self, driver, element):
        try:
            driver.execute_script("arguments[0].click();", element)
        except Exception:
            try:
                element.click()
            except Exception:
                pass

    def _human_type(self, element, text):
        for char in text:
            element.send_keys(char)
            time.sleep(random.uniform(0.03, 0.10))

    def _handle_post_login(self, driver):
        from selenium.webdriver.common.by import By

        try:
            btns = driver.find_elements(By.ID, "idSIButton9")
            if btns and btns[0].is_displayed():
                self._safe_click(driver, btns[0])
                time.sleep(2)
        except Exception:
            pass

        try:
            cb = driver.find_elements(By.ID, "KmsiCheckboxField")
            if cb and cb[0].is_displayed():
                self._safe_click(driver, cb[0])
                time.sleep(0.5)
            no = driver.find_elements(By.ID, "idBtn_Back")
            if no and no[0].is_displayed():
                self._safe_click(driver, no[0])
                time.sleep(2)
        except Exception:
            pass

        try:
            al = driver.find_elements(By.ID, "btnAskLater")
            if al and al[0].is_displayed():
                self._safe_click(driver, al[0])
                time.sleep(2)
        except Exception:
            pass

    def _handle_consent(self, driver):
        from selenium.webdriver.common.by import By

        try:
            for btn in driver.find_elements(By.CSS_SELECTOR, 'input[type="submit"]'):
                if btn.is_displayed():
                    self._safe_click(driver, btn)
                    time.sleep(3)
                    break
        except Exception:
            pass

        try:
            for btn in driver.find_elements(By.TAG_NAME, "button"):
                if btn.is_displayed():
                    txt = btn.text.lower()
                    if any(kw in txt for kw in ["accept", "continue", "allow", "yes"]):
                        self._safe_click(driver, btn)
                        time.sleep(3)
                        break
        except Exception:
            pass

    def _screenshot(self, driver, label):
        try:
            os.makedirs("screenshots", exist_ok=True)
            driver.save_screenshot(
                f"screenshots/{self.screenshot_prefix}_{self.worker_id}_{label}_"
                f"{datetime.now().strftime('%H%M%S')}.png"
            )
        except Exception:
            pass
