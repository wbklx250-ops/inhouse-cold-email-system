"""Simple browser helper for Selenium automation (restored)."""

import os
import tempfile
import uuid
import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

logger = logging.getLogger(__name__)

SCREENSHOT_DIR = os.environ.get("SCREENSHOT_DIR", "/tmp/screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def create_driver(headless: bool = True) -> webdriver.Chrome:
    """Create a Chrome driver with basic stability options."""
    opts = Options()

    # Headless mode (default True for production)
    if headless:
        opts.add_argument("--headless=new")

    # Basic stability options
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-infobars")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-popup-blocking")

    # Avoid detection
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    # Enable performance logging (for network token extraction)
    caps = DesiredCapabilities.CHROME
    caps["goog:loggingPrefs"] = {"performance": "ALL"}
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    # Unique profile for isolation (lightweight, no BrowserWorker)
    user_data_dir = os.path.join(tempfile.gettempdir(), f"chrome_profile_{uuid.uuid4().hex[:8]}")
    opts.add_argument(f"--user-data-dir={user_data_dir}")

    return webdriver.Chrome(options=opts)


def cleanup_driver(driver: webdriver.Chrome) -> None:
    """Close the driver safely."""
    try:
        driver.quit()
    except Exception:
        pass


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
        logger.error(f"Screenshot failed: {e}")
        return ""