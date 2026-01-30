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

    # Disable password manager popups
    opts.add_experimental_option(
        "prefs",
        {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
            "profile.password_manager_leak_detection": False,
        },
    )

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
    """Close the driver safely and force kill any orphaned Chrome processes."""
    import subprocess
    import platform
    import time

    # First try graceful quit
    try:
        driver.quit()
    except Exception as e:
        logger.warning("Driver quit failed: %s", e)

    # Give it a moment to clean up
    time.sleep(2)

    # Force kill orphaned Chrome processes on Windows
    if platform.system() == "Windows":
        try:
            # Kill ChromeDriver processes
            subprocess.run(
                ["taskkill", "/F", "/IM", "chromedriver.exe"],
                capture_output=True,
                timeout=10
            )
        except Exception as e:
            logger.debug("ChromeDriver kill: %s", e)
        
        # Kill zombie Chrome processes (only our automation ones with specific profile pattern)
        try:
            result = subprocess.run(
                ["wmic", "process", "where", "name='chrome.exe'", "get", "commandline,processid"],
                capture_output=True,
                text=True,
                timeout=10
            )
            # Look for our temp profile pattern and kill those
            for line in result.stdout.split('\n'):
                if 'chrome_profile_' in line and 'user-data-dir' in line:
                    # Extract PID and kill
                    parts = line.strip().split()
                    if parts:
                        try:
                            pid = parts[-1]
                            subprocess.run(
                                ["taskkill", "/F", "/PID", pid],
                                capture_output=True,
                                timeout=5
                            )
                        except Exception:
                            pass
        except Exception as e:
            logger.debug("Chrome cleanup: %s", e)
    else:
        # Linux/Mac - use pkill
        try:
            subprocess.run(["pkill", "-f", "chromedriver"], capture_output=True, timeout=5)
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