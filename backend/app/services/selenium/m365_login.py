"""
M365 Admin Portal Login - JUST LOGIN, NOTHING ELSE.
"""
import time
import os
import pyotp
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
import logging

logger = logging.getLogger(__name__)
SCREENSHOT_DIR = os.environ.get("SCREENSHOT_DIR", "C:/temp/screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def create_browser():
    """Create Chrome browser."""
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    prefs = {"credentials_enable_service": False, "profile.password_manager_enabled": False}
    options.add_experimental_option("prefs", prefs)
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    
    driver = webdriver.Chrome(options=options)
    driver.implicitly_wait(10)
    return driver


def screenshot(driver, name):
    """Save screenshot."""
    path = f"{SCREENSHOT_DIR}/{name}_{int(time.time())}.png"
    driver.save_screenshot(path)
    logger.info(f"Screenshot: {path}")
    return path


def login_to_m365(admin_email: str, admin_password: str, totp_secret: str):
    """
    Login to M365 Admin Portal.
    Returns (driver, success, error_message)
    """
    driver = None
    
    try:
        driver = create_browser()
        logger.info(f"Opening admin.microsoft.com...")
        driver.get("https://admin.microsoft.com")
        time.sleep(3)
        screenshot(driver, "01_start")
        
        # Enter email
        logger.info(f"Entering email: {admin_email}")
        email_field = driver.find_element(By.NAME, "loginfmt")
        email_field.clear()
        email_field.send_keys(admin_email)
        email_field.send_keys(Keys.RETURN)
        time.sleep(3)
        screenshot(driver, "02_after_email")
        
        # Enter password
        logger.info("Entering password...")
        password_field = driver.find_element(By.NAME, "passwd")
        password_field.clear()
        password_field.send_keys(admin_password)
        password_field.send_keys(Keys.RETURN)
        time.sleep(3)
        screenshot(driver, "03_after_password")
        
        # Check for MFA
        try:
            totp_field = driver.find_element(By.NAME, "otc")
            totp = pyotp.TOTP(totp_secret)
            code = totp.now()
            logger.info(f"Entering TOTP code: {code[:2]}***")
            totp_field.send_keys(code)
            totp_field.send_keys(Keys.RETURN)
            time.sleep(3)
            screenshot(driver, "04_after_mfa")
        except:
            logger.info("No MFA prompt")
        
        # Handle "Stay signed in?"
        try:
            no_btn = driver.find_element(By.ID, "idBtn_Back")
            no_btn.click()
            time.sleep(2)
        except:
            pass
        
        screenshot(driver, "05_after_login")
        
        # Verify login worked
        time.sleep(3)
        current_url = driver.current_url
        logger.info(f"Current URL: {current_url}")
        
        if "admin" in current_url.lower():
            logger.info("LOGIN SUCCESSFUL!")
            return driver, True, None
        else:
            logger.error(f"LOGIN FAILED - unexpected URL: {current_url}")
            return driver, False, f"Unexpected URL: {current_url}"
            
    except Exception as e:
        logger.error(f"Login error: {e}")
        if driver:
            screenshot(driver, "error")
        return driver, False, str(e)


# TEST FUNCTION
def test_login():
    """Test login with hardcoded credentials."""
    driver, success, error = login_to_m365(
        admin_email="admin@YourTenant.onmicrosoft.com",
        admin_password="YourPassword",
        totp_secret="YourTOTPSecret"
    )
    
    if success:
        print("LOGIN WORKED!")
        input("Press Enter to close browser...")
    else:
        print(f"LOGIN FAILED: {error}")
    
    if driver:
        driver.quit()


if __name__ == "__main__":
    test_login()
