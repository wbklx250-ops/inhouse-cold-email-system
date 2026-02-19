"""
Step 5 Helpers — Chrome lifecycle, universal click/dismiss helpers, page state detection.

Used by step5_phases.py and step5_orchestrator.py.
"""

import time
import re
import os
import gc
import signal
import shutil
import tempfile
import uuid
import subprocess
import pyotp
import logging
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, StaleElementReferenceException,
    ElementClickInterceptedException, WebDriverException,
)

logger = logging.getLogger(__name__)

SCREENSHOT_DIR = os.environ.get("SCREENSHOT_DIR", "/tmp/screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

PHASE_RETRIES = int(os.getenv("STEP5_PHASE_RETRIES", "3"))
DNS_WAIT = int(os.getenv("STEP5_DNS_WAIT_SECONDS", "45"))
DKIM_WAIT = int(os.getenv("STEP5_DKIM_WAIT_SECONDS", "90"))
VERIFY_RETRY_WAIT = int(os.getenv("STEP5_VERIFY_RETRY_WAIT", "60"))


# ============================================================
# CHROME LIFECYCLE
# ============================================================

def kill_zombie_chrome():
    """Kill ALL orphaned Chrome/Chromium processes. Silent on Windows."""
    for pattern in ["chrome", "chromium", "chromedriver"]:
        try:
            subprocess.run(["pkill", "-9", "-f", pattern], capture_output=True, timeout=5)
        except Exception:
            pass
    gc.collect()


def create_chrome(headless=True, max_retries=3):
    """
    Create Chrome with retry. Returns (driver, profile_dir).
    Caller MUST call destroy_chrome() in finally block.
    """
    kill_zombie_chrome()

    for attempt in range(1, max_retries + 1):
        profile_dir = None
        try:
            profile_dir = tempfile.mkdtemp(prefix=f"step5_{uuid.uuid4().hex[:6]}_")

            options = webdriver.ChromeOptions()
            if headless:
                options.add_argument("--headless=new")

            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-infobars")
            options.add_argument("--disable-notifications")
            options.add_argument("--disable-popup-blocking")
            options.add_argument("--disable-translate")
            options.add_argument("--disable-background-networking")
            options.add_argument("--disable-sync")
            options.add_argument("--disable-default-apps")
            options.add_argument("--no-first-run")
            options.add_argument("--disable-software-rasterizer")
            options.add_argument("--js-flags=--max-old-space-size=256")
            options.add_argument("--single-process")
            options.add_argument(f"--user-data-dir={profile_dir}")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)

            chrome_path = os.environ.get("CHROME_PATH", "/usr/bin/chromium")
            chromedriver_path = os.environ.get("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")
            if os.path.exists(chrome_path):
                options.binary_location = chrome_path

            service = Service(executable_path=chromedriver_path) if os.path.exists(chromedriver_path) else Service()

            driver = webdriver.Chrome(service=service, options=options)
            driver.implicitly_wait(15)
            driver.set_page_load_timeout(90)
            driver.set_script_timeout(60)

            logger.info(f"Chrome started (attempt {attempt})")
            return driver, profile_dir

        except Exception as e:
            logger.warning(f"Chrome start failed (attempt {attempt}/{max_retries}): {e}")
            if profile_dir:
                shutil.rmtree(profile_dir, ignore_errors=True)
            if attempt < max_retries:
                kill_zombie_chrome()
                time.sleep(10)
            else:
                raise RuntimeError(f"Chrome failed to start after {max_retries} attempts: {e}")

    raise RuntimeError("Unreachable")


def destroy_chrome(driver, profile_dir):
    """AGGRESSIVELY destroy Chrome. Call in finally block ALWAYS."""
    if driver:
        try:
            driver.quit()
        except Exception:
            pass
        try:
            if hasattr(driver, 'service') and driver.service.process:
                os.kill(driver.service.process.pid, signal.SIGKILL)
        except Exception:
            pass
    if profile_dir:
        shutil.rmtree(profile_dir, ignore_errors=True)
    gc.collect()


def save_screenshot(driver, domain, step):
    """Save debug screenshot. Never throws."""
    try:
        safe = domain.replace(".", "_")
        path = os.path.join(SCREENSHOT_DIR, f"{step}_{safe}_{int(time.time())}.png")
        driver.save_screenshot(path)
        logger.debug(f"Screenshot: {path}")
    except Exception:
        pass


# ============================================================
# UNIVERSAL HELPERS
# ============================================================

def dismiss_popups(driver):
    """Dismiss Teaching Bubbles, cookie banners, notification bars, and overlays."""
    selectors = [
        "//div[contains(@class, 'ms-TeachingBubble')]//button",
        "//div[contains(@class, 'ms-TeachingBubble')]//button[contains(@class, 'close')]",
        "//button[@aria-label='Close']",
        "//button[@aria-label='Dismiss']",
        "//button[@aria-label='Got it']",
        "//button[contains(text(), 'Accept')]",
        "//button[contains(text(), 'OK')]",
        "//button[@id='acceptButton']",
        "//div[contains(@class, 'ms-MessageBar')]//button",
    ]
    for sel in selectors:
        try:
            elements = driver.find_elements(By.XPATH, sel)
            for el in elements:
                try:
                    driver.execute_script("arguments[0].click();", el)
                    time.sleep(0.3)
                except Exception:
                    pass
        except Exception:
            pass


def safe_click(driver, element, description, domain=""):
    """Click element with 3 fallback strategies."""
    dismiss_popups(driver)

    # Strategy 1: Normal click
    try:
        element.click()
        logger.debug(f"[{domain}] Clicked {description} (normal)")
        return True
    except (ElementClickInterceptedException, WebDriverException):
        pass

    # Strategy 2: ActionChains
    try:
        ActionChains(driver).move_to_element(element).click().perform()
        logger.debug(f"[{domain}] Clicked {description} (ActionChains)")
        return True
    except Exception:
        pass

    # Strategy 3: JavaScript
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        time.sleep(0.3)
        driver.execute_script("arguments[0].click();", element)
        logger.debug(f"[{domain}] Clicked {description} (JavaScript)")
        return True
    except Exception as e:
        logger.warning(f"[{domain}] All click strategies failed for {description}: {e}")
        save_screenshot(driver, domain, f"click_failed_{description.replace(' ', '_')}")
        return False


def find_and_click(driver, selectors, description, domain="", timeout=15):
    """Find element from multiple selectors, then safe-click it. Retries 3 times."""
    for attempt in range(3):
        dismiss_popups(driver)

        for selector_type, selector_value in selectors:
            try:
                el = WebDriverWait(driver, timeout // 3).until(
                    EC.presence_of_element_located((selector_type, selector_value))
                )
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                time.sleep(0.3)
                if safe_click(driver, el, description, domain):
                    return True
            except (TimeoutException, NoSuchElementException, StaleElementReferenceException):
                continue

        if attempt < 2:
            time.sleep(2)

    logger.warning(f"[{domain}] Could not find/click: {description}")
    return False


def wait_for_text(driver, texts, timeout=30):
    """Wait until any of the given texts appear on page. Returns matching text or None."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            page = driver.find_element(By.TAG_NAME, "body").text.lower()
            for t in texts:
                if t.lower() in page:
                    return t
        except Exception:
            pass
        time.sleep(2)
    return None


def get_fresh_totp(totp_secret):
    """Generate TOTP code, waiting if close to window boundary."""
    totp = pyotp.TOTP(totp_secret)
    remaining = totp.interval - (int(time.time()) % totp.interval)
    if remaining < 5:
        logger.info(f"TOTP expires in {remaining}s, waiting for fresh code...")
        time.sleep(remaining + 1)
    code = totp.now()
    remaining = totp.interval - (int(time.time()) % totp.interval)
    logger.info(f"TOTP code generated, valid for {remaining}s")
    return code


# ============================================================
# PAGE STATE DETECTION
# ============================================================

def detect_page_state(driver, domain):
    """Detect which page of the M365 domain wizard we're on."""
    time.sleep(2)
    try:
        page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
    except Exception:
        return "error"

    if "domain setup is complete" in page_text or "is all set up" in page_text:
        return "complete"
    if "already been added" in page_text or "already exists" in page_text:
        return "already_exists"
    if "verify you own" in page_text or "verify your domain" in page_text or "add a txt record" in page_text:
        return "verification"
    if "how do you want to connect your domain" in page_text:
        return "connect_domain"
    if "add dns records" in page_text or "update dns settings" in page_text:
        return "dns_records"
    if any(x in page_text for x in ["didn't detect", "couldn't find", "records not found"]):
        return "dns_not_propagated"
    if "pick an account" in page_text or "choose an account" in page_text:
        return "account_picker"
    if "enter password" in page_text or "sign in" in page_text:
        return "login"

    logger.warning(f"[{domain}] Unknown page state")
    save_screenshot(driver, domain, "unknown_page_state")
    return "unknown"
