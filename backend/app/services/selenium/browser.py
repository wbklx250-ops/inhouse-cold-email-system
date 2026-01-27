"""Browser management for Selenium automation."""

import os
import shutil
import tempfile
import time
import uuid
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

SCREENSHOT_DIR = os.environ.get("SCREENSHOT_DIR", "/tmp/screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def create_driver(headless: bool = True, profile_tag: str = None) -> webdriver.Chrome:
    """Create a Chrome driver with anti-detection settings and isolated profile."""
    opts = Options()
    
    if headless:
        opts.add_argument("--headless=new")
    
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-extensions")

    unique_tag = profile_tag or str(uuid.uuid4())
    profile_dir = tempfile.mkdtemp(prefix=f"chrome-profile-{unique_tag}-")
    opts.add_argument(f"--user-data-dir={profile_dir}")
    opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    
    # For Railway/Linux - use system chromium
    chrome_path = os.environ.get("CHROME_PATH", "/usr/bin/chromium")
    if os.path.exists(chrome_path):
        opts.binary_location = chrome_path
    
    driver = webdriver.Chrome(options=opts)
    driver._profile_dir = profile_dir
    
    # Remove webdriver flag
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    driver.implicitly_wait(5)
    
    return driver


def cleanup_driver(driver: webdriver.Chrome) -> None:
    """Close driver and delete its temp profile directory."""
    profile_dir = getattr(driver, "_profile_dir", None)
    try:
        driver.quit()
    except Exception:
        pass

    if profile_dir and os.path.exists(profile_dir):
        shutil.rmtree(profile_dir, ignore_errors=True)


def take_screenshot(driver: webdriver.Chrome, name: str) -> str:
    """Take screenshot and return path."""
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{name}.png"
    path = os.path.join(SCREENSHOT_DIR, filename)
    
    try:
        driver.save_screenshot(path)
        return path
    except Exception as e:
        print(f"Screenshot failed: {e}")
        return ""