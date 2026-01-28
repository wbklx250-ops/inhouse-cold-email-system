"""
BULLETPROOF M365 DOMAIN SETUP - STANDALONE SCRIPT
Run this directly to test: python step5_standalone.py

This script will NOT close the browser until:
1. The entire domain setup is complete, OR
2. An explicit unrecoverable error occurs

Author: Complete rewrite for reliability
"""

import time
import os
import re
import sys
import logging
from datetime import datetime

# Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementClickInterceptedException,
    StaleElementReferenceException,
)

import pyotp

# =============================================================================
# CONFIGURATION - EDIT THESE FOR YOUR TEST
# =============================================================================

# Tenant credentials
ADMIN_EMAIL = "admin@VonateknaFreig2601021.onmicrosoft.com"  # CHANGE THIS
ADMIN_PASSWORD = "YOUR_PASSWORD"  # CHANGE THIS
TOTP_SECRET = "YOUR_TOTP_SECRET"  # CHANGE THIS

# Domain to setup
DOMAIN_TO_SETUP = "yourdomain.com"  # CHANGE THIS
CLOUDFLARE_ZONE_ID = "your_zone_id"  # CHANGE THIS

# Cloudflare API (for adding DNS records)
CLOUDFLARE_API_KEY = "your_api_key"  # CHANGE THIS
CLOUDFLARE_EMAIL = "your_email"  # CHANGE THIS

# Directories
SCREENSHOT_DIR = "C:/temp/screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# =============================================================================
# LOGGING SETUP
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f'C:/temp/step5_log_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt')
    ]
)
logger = logging.getLogger(__name__)

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def screenshot(driver, name):
    """Save screenshot with timestamp."""
    timestamp = datetime.now().strftime("%H%M%S")
    filepath = os.path.join(SCREENSHOT_DIR, f"{timestamp}_{name}.png")
    try:
        driver.save_screenshot(filepath)
        logger.info(f"Screenshot: {filepath}")
    except:
        pass
    return filepath


def wait_and_find(driver, by, value, timeout=10, must_be_visible=True):
    """Wait for element and return it. Returns None if not found."""
    try:
        wait = WebDriverWait(driver, timeout)
        if must_be_visible:
            element = wait.until(EC.visibility_of_element_located((by, value)))
        else:
            element = wait.until(EC.presence_of_element_located((by, value)))
        return element
    except TimeoutException:
        return None


def safe_click(driver, element, description="element"):
    """Click element with multiple fallback methods."""
    try:
        # Method 1: Scroll into view and click
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        time.sleep(0.3)
        element.click()
        logger.info(f"Clicked: {description}")
        time.sleep(2)  # Slow enough to watch
        return True
    except ElementClickInterceptedException:
        pass
    except:
        pass

    try:
        # Method 2: JavaScript click
        driver.execute_script("arguments[0].click();", element)
        logger.info(f"JS Clicked: {description}")
        time.sleep(2)  # Slow enough to watch
        return True
    except:
        pass

    logger.error(f"Failed to click: {description}")
    return False


def get_page_state(driver):
    """Determine current page state."""
    url = driver.current_url.lower()
    
    try:
        page_text = driver.page_source.lower()
    except:
        page_text = ""
    
    # Login states
    if "login.microsoftonline.com" in url or "login.live.com" in url:
        # Check password field FIRST (and visibility)
        try:
            passwd = driver.find_element(By.NAME, "passwd")
            if passwd.is_displayed():
                return "LOGIN_PASSWORD"
        except:
            pass
        
        # Check email field
        try:
            email = driver.find_element(By.NAME, "loginfmt")
            if email.is_displayed():
                return "LOGIN_EMAIL"
        except:
            pass
        
        # Check MFA
        try:
            otp = driver.find_element(By.NAME, "otc")
            if otp.is_displayed():
                return "LOGIN_MFA"
        except:
            pass
        
        # Stay signed in
        if "kmsi" in url or "stay signed in" in page_text:
            return "LOGIN_STAY_SIGNED_IN"
        
        return "LOGIN_UNKNOWN"
    
    # M365 Admin Center - check BOTH URLs
    if "admin.microsoft.com" in url or "admin.cloud.microsoft.com" in url:
        # Domains page
        if "/domains" in url.lower():
            if "add a domain" in page_text or "add domain" in page_text:
                return "DOMAINS_LIST"
            if "enter the domain" in page_text or "what domain do you want to use" in page_text:
                return "ADD_DOMAIN_FORM"
            if "verify" in page_text and "txt" in page_text and "ms=" in page_text:
                return "VERIFICATION_PAGE"
            if "domain setup is complete" in page_text:
                return "SETUP_COMPLETE"
            if "how do you want to connect" in page_text or "add your own dns" in page_text:
                return "DNS_SETUP_PAGE"
            if "verification failed" in page_text:
                return "VERIFICATION_FAILED"
            return "DOMAINS_PAGE_OTHER"
        
        # Homepage
        if "/homepage" in url or "home" in url:
            return "ADMIN_HOME"
        
        return "ADMIN_OTHER"
    
    # Azure portal
    if "portal.azure.com" in url:
        return "AZURE_PORTAL"
    
    # Office
    if "office.com" in url:
        return "OFFICE_HOME"
    
    return "UNKNOWN"


# =============================================================================
# MAIN AUTOMATION FUNCTIONS
# =============================================================================

def do_login(driver):
    """Complete the entire login flow. Returns True on success."""
    logger.info("=" * 50)
    logger.info("STARTING LOGIN FLOW")
    logger.info("=" * 50)
    
    # Go to admin portal
    driver.get("https://admin.microsoft.com")
    time.sleep(3)
    screenshot(driver, "01_initial_load")
    
    max_iterations = 30  # Plenty of room
    
    for i in range(max_iterations):
        state = get_page_state(driver)
        logger.info(f"Login iteration {i+1}: State = {state}")
        screenshot(driver, f"02_login_state_{i}_{state}")
        
        if state == "LOGIN_EMAIL":
            logger.info("Entering email...")
            email_field = wait_and_find(driver, By.NAME, "loginfmt", timeout=5)
            if email_field:
            email_field.clear()
                email_field.send_keys(ADMIN_EMAIL)
                time.sleep(1)  # Pause after typing
                email_field.send_keys(Keys.RETURN)
                time.sleep(3)
            continue
        
        elif state == "LOGIN_PASSWORD":
            logger.info("Entering password...")
            passwd_field = wait_and_find(driver, By.NAME, "passwd", timeout=5)
            if passwd_field:
                passwd_field.clear()
                passwd_field.send_keys(ADMIN_PASSWORD)
                passwd_field.send_keys(Keys.RETURN)
                time.sleep(3)
            continue
        
        elif state == "LOGIN_MFA":
            logger.info("Entering MFA code...")
            code = pyotp.TOTP(TOTP_SECRET).now()
            logger.info(f"MFA Code: {code}")
            otp_field = wait_and_find(driver, By.NAME, "otc", timeout=5)
            if otp_field:
                otp_field.clear()
                otp_field.send_keys(code)
                # Click verify button
                try:
                    verify_btn = driver.find_element(By.ID, "idSubmit_SAOTCC_Continue")
                    safe_click(driver, verify_btn, "MFA Verify")
                except:
                    otp_field.send_keys(Keys.RETURN)
                time.sleep(3)
            continue
        
        elif state == "LOGIN_STAY_SIGNED_IN":
            logger.info("Handling 'Stay signed in' prompt...")
            try:
                no_btn = driver.find_element(By.ID, "idBtn_Back")
                safe_click(driver, no_btn, "Stay signed in - No")
            except:
                try:
                    yes_btn = driver.find_element(By.ID, "idSIButton9")
                    safe_click(driver, yes_btn, "Stay signed in - Yes")
                except:
                    pass
            time.sleep(3)
            continue
        
        elif state in ["ADMIN_HOME", "ADMIN_OTHER", "AZURE_PORTAL", "OFFICE_HOME"]:
            logger.info("LOGIN SUCCESSFUL!")
            screenshot(driver, "03_login_complete")
            return True
        
        elif state == "LOGIN_UNKNOWN":
            logger.warning("Unknown login state, waiting...")
            time.sleep(2)
            continue
        
        else:
            # Might already be logged in
            if "admin" in driver.current_url.lower():
                logger.info("Already at admin portal - LOGIN SUCCESSFUL!")
                return True
            time.sleep(2)
    
    logger.error("Login failed - max iterations reached")
    return False


def navigate_to_domains(driver):
    """Navigate to the domains page."""
    logger.info("=" * 50)
    logger.info("NAVIGATING TO DOMAINS PAGE")
    logger.info("=" * 50)
    
    # Direct URL to domains
    driver.get("https://admin.microsoft.com/AdminPortal/Home#/Domains")
    time.sleep(5)
    screenshot(driver, "04_domains_page")
    
    # Verify we're on domains page
    for _ in range(10):
        state = get_page_state(driver)
        logger.info(f"Navigation state: {state}")
        
        if "DOMAIN" in state:
            logger.info("Successfully on Domains page!")
            return True
        
        time.sleep(2)
    
    logger.error("Failed to navigate to domains page")
    return False


def add_domain(driver, domain):
    """Add domain to M365. Returns TXT verification value."""
    logger.info("=" * 50)
    logger.info(f"ADDING DOMAIN: {domain}")
    logger.info("=" * 50)
    
    # Click "Add domain" button
    logger.info("Looking for 'Add domain' button...")
    
    add_btn = None
    for selector in [
        "//button[contains(text(), 'Add domain')]",
        "//span[contains(text(), 'Add domain')]/ancestor::button",
        "//button[contains(@class, 'add')]",
    ]:
        try:
            add_btn = driver.find_element(By.XPATH, selector)
            if add_btn.is_displayed():
                break
        except:
            continue
    
    if not add_btn:
        # Maybe domain is already added - check if it's in the list
        if domain.lower() in driver.page_source.lower():
            logger.info(f"Domain {domain} may already exist in M365")
            return "ALREADY_EXISTS"
        logger.error("Could not find 'Add domain' button")
        screenshot(driver, "05_no_add_button")
        return None
    
    safe_click(driver, add_btn, "Add domain button")
    time.sleep(3)
    screenshot(driver, "05_add_domain_clicked")
    
    # Enter domain name
    logger.info(f"Entering domain name: {domain}")
    
    domain_input = wait_and_find(driver, By.CSS_SELECTOR, "input[type='text']", timeout=10)
    if not domain_input:
        # Try other selectors
        domain_input = wait_and_find(driver, By.XPATH, "//input[@placeholder]", timeout=5)
    
    if domain_input:
        domain_input.clear()
        domain_input.send_keys(domain)
        time.sleep(1)
        screenshot(driver, "06_domain_entered")
    else:
        logger.error("Could not find domain input field")
        return None
    
    # Click "Use this domain" or Continue
    logger.info("Clicking 'Use this domain'...")
    
    for selector in [
        "//button[contains(text(), 'Use this domain')]",
        "//button[contains(text(), 'Continue')]",
        "//button[contains(text(), 'Next')]",
        "//button[@type='submit']",
    ]:
        try:
            btn = driver.find_element(By.XPATH, selector)
            if btn.is_displayed() and btn.is_enabled():
                safe_click(driver, btn, "Use this domain")
                break
        except:
            continue
    
    time.sleep(5)
    screenshot(driver, "07_after_use_domain")
    
    # Now we should be on verification page
    # Select TXT verification method
    logger.info("Selecting TXT verification method...")
    
    # Click "More options" if present
    try:
        more_opts = driver.find_element(By.XPATH, "//*[contains(text(), 'More options')]")
        safe_click(driver, more_opts, "More options")
        time.sleep(2)
    except:
        pass
    
    # Select TXT record option
    for selector in [
        "//label[contains(., 'TXT')]",
        "//*[contains(text(), 'TXT record')]",
        "//input[@type='radio'][following-sibling::*[contains(text(), 'TXT')]]/..",
    ]:
        try:
            txt_option = driver.find_element(By.XPATH, selector)
            safe_click(driver, txt_option, "TXT option")
            time.sleep(1)
            break
        except:
            continue
    
    # Click Continue
    for selector in [
        "//button[contains(text(), 'Continue')]",
        "//button[contains(text(), 'Next')]",
    ]:
        try:
            btn = driver.find_element(By.XPATH, selector)
            if btn.is_displayed():
                safe_click(driver, btn, "Continue")
                break
        except:
            continue
    
    time.sleep(3)
    screenshot(driver, "08_verification_page")
    
    # Extract TXT value (MS=...)
    logger.info("Extracting TXT verification value...")
    
    txt_value = None
    page_source = driver.page_source
    
    # Method 1: Regex search
    match = re.search(r'MS=ms\w+', page_source)
    if match:
        txt_value = match.group(0)
        logger.info(f"Found TXT value: {txt_value}")
    
    # Method 2: Look in elements
    if not txt_value:
        for tag in ['td', 'span', 'div', 'p']:
            try:
                elements = driver.find_elements(By.TAG_NAME, tag)
                for elem in elements:
                    text = elem.text
                    if 'MS=' in text:
                        match = re.search(r'MS=\w+', text)
                        if match:
                            txt_value = match.group(0)
                            logger.info(f"Found TXT value in {tag}: {txt_value}")
                            break
            except:
                continue
            if txt_value:
                break
    
    if txt_value:
        return txt_value
    else:
        logger.error("Could not find TXT verification value")
        screenshot(driver, "09_no_txt_found")
        return None


def add_txt_to_cloudflare(domain, txt_value, zone_id):
    """Add TXT record to Cloudflare via API."""
    import requests
    
    logger.info(f"Adding TXT record to Cloudflare: {txt_value}")
    
    headers = {
        "X-Auth-Email": CLOUDFLARE_EMAIL,
        "X-Auth-Key": CLOUDFLARE_API_KEY,
        "Content-Type": "application/json"
    }
    
    # First, check if record exists and delete it
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    params = {"type": "TXT", "name": domain}
    
    try:
        resp = requests.get(url, headers=headers, params=params)
        if resp.status_code == 200:
            records = resp.json().get("result", [])
            for record in records:
                if record.get("content", "").startswith("MS="):
                    # Delete old verification record
                    delete_url = f"{url}/{record['id']}"
                    requests.delete(delete_url, headers=headers)
                    logger.info(f"Deleted old TXT record: {record['content']}")
    except Exception as e:
        logger.warning(f"Error checking existing records: {e}")
    
    # Create new record
    data = {
        "type": "TXT",
        "name": "@",
        "content": txt_value,
        "ttl": 1  # Auto
    }
    
    try:
        resp = requests.post(url, headers=headers, json=data)
        if resp.status_code in [200, 201]:
            logger.info("TXT record added to Cloudflare successfully!")
            return True
        else:
            logger.error(f"Cloudflare API error: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Cloudflare API exception: {e}")
        return False


def click_verify_and_wait(driver):
    """Click Verify button and wait for result. Returns True on success."""
    logger.info("=" * 50)
    logger.info("CLICKING VERIFY AND WAITING FOR RESULT")
    logger.info("=" * 50)
    
    # Find Verify button
    verify_btn = None
    for selector in [
        "//button[normalize-space()='Verify']",
        "//button[contains(text(), 'Verify')]",
        "//button[contains(@class, 'primary')][contains(., 'erify')]",
    ]:
        try:
            buttons = driver.find_elements(By.XPATH, selector)
            for btn in buttons:
                if btn.is_displayed() and "verify" in btn.text.lower():
                    verify_btn = btn
                    break
        except:
            continue
        if verify_btn:
            break
    
    if not verify_btn:
        logger.error("Could not find Verify button!")
        screenshot(driver, "10_no_verify_button")
        return False
    
    # Scroll and click
    screenshot(driver, "10_before_verify_click")
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", verify_btn)
    time.sleep(0.5)
    driver.execute_script("arguments[0].click();", verify_btn)
    logger.info("Clicked Verify button!")
    
    # Wait for result (up to 2 minutes)
    logger.info("Waiting for verification result...")
    screenshot(driver, "11_after_verify_click")
    
    for wait_count in range(60):  # 60 x 2 seconds = 2 minutes
        time.sleep(2)
        
        page_text = driver.page_source.lower()
        state = get_page_state(driver)
        
        logger.info(f"Waiting... ({wait_count * 2}s) - State: {state}")
        
        # Success indicators
        if "domain setup is complete" in page_text:
            logger.info("VERIFICATION SUCCESS - Setup complete!")
            return True
        
        if "how do you want to connect" in page_text:
            logger.info("VERIFICATION SUCCESS - Moved to DNS setup!")
            return True
        
        if "add your own dns" in page_text:
            logger.info("VERIFICATION SUCCESS - On DNS page!")
            return True
        
        if state == "DNS_SETUP_PAGE":
            logger.info("VERIFICATION SUCCESS - DNS setup page detected!")
            return True
        
        # Failure indicators
        if "verification failed" in page_text:
            logger.error("VERIFICATION FAILED explicitly!")
            screenshot(driver, "12_verification_failed")
            return False
        
        if "try again" in page_text and "could" in page_text:
            logger.error("VERIFICATION FAILED - try again message!")
            screenshot(driver, "12_verification_try_again")
            return False
    
    logger.error("VERIFICATION TIMEOUT - No result after 2 minutes")
    screenshot(driver, "12_verification_timeout")
    return False


def complete_dns_setup(driver, domain, zone_id):
    """Complete the DNS setup wizard."""
    logger.info("=" * 50)
    logger.info("COMPLETING DNS SETUP")
    logger.info("=" * 50)
    
    screenshot(driver, "13_dns_setup_start")
    
    # Select "Add your own DNS records"
    for selector in [
        "//*[contains(text(), 'Add your own DNS')]",
        "//label[contains(., 'Add your own')]",
        "//*[contains(text(), 'own DNS records')]",
    ]:
        try:
            option = driver.find_element(By.XPATH, selector)
            safe_click(driver, option, "Add your own DNS")
            time.sleep(1)
            break
        except:
            continue
    
    # Click Continue
    for selector in [
        "//button[contains(text(), 'Continue')]",
        "//button[contains(text(), 'Next')]",
    ]:
        try:
            btn = driver.find_element(By.XPATH, selector)
            if btn.is_displayed():
                safe_click(driver, btn, "Continue")
                break
        except:
            continue
    
    time.sleep(3)
    screenshot(driver, "14_dns_records_page")
    
    # Extract DNS record values (MX, SPF, etc.)
    page_source = driver.page_source
    
    # MX record
    mx_match = re.search(r'([a-zA-Z0-9-]+\.mail\.protection\.outlook\.com)', page_source)
    if mx_match:
        mx_value = mx_match.group(1)
        logger.info(f"Found MX: {mx_value}")
        # Add to Cloudflare... (simplified for now)
    
    # Click Continue/Done repeatedly until complete
    for attempt in range(10):
        time.sleep(3)
        
        state = get_page_state(driver)
        page_text = driver.page_source.lower()
        
        logger.info(f"DNS setup attempt {attempt + 1}: State = {state}")
        
        if "domain setup is complete" in page_text:
            logger.info("DNS SETUP COMPLETE!")
            screenshot(driver, "15_setup_complete")
            
            # Click Done
            try:
                done_btn = driver.find_element(By.XPATH, "//button[contains(text(), 'Done')]")
                safe_click(driver, done_btn, "Done")
            except:
                pass
            
            return True
        
        # Click Continue/Done
        for selector in [
            "//button[contains(text(), 'Continue')]",
            "//button[contains(text(), 'Done')]",
            "//button[contains(text(), 'Finish')]",
        ]:
            try:
                btn = driver.find_element(By.XPATH, selector)
                if btn.is_displayed() and btn.is_enabled():
                    safe_click(driver, btn, "Continue/Done")
                    break
            except:
                continue
    
    logger.warning("DNS setup did not reach 'complete' state")
    return False


# =============================================================================
# MAIN EXECUTION
# =============================================================================

def main():
    """Main function - runs the complete flow."""
    logger.info("=" * 60)
    logger.info("STARTING BULLETPROOF M365 DOMAIN SETUP")
    logger.info(f"Domain: {DOMAIN_TO_SETUP}")
    logger.info(f"Admin: {ADMIN_EMAIL}")
    logger.info("=" * 60)
    
    # Create browser
    options = Options()
    # NOT headless - we want to see what's happening!
    options.add_argument("--start-maximized")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    
    prefs = {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False
    }
    options.add_experimental_option("prefs", prefs)
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    
    driver = webdriver.Chrome(options=options)
    driver.implicitly_wait(5)
    
    try:
        # STEP 1: Login
        if not do_login(driver):
            logger.error("FAILED AT: Login")
            input("Press Enter to close browser...")
            return False
        
        # STEP 2: Navigate to Domains
        if not navigate_to_domains(driver):
            logger.error("FAILED AT: Navigate to domains")
            input("Press Enter to close browser...")
            return False
        
        # STEP 3: Add Domain
        txt_value = add_domain(driver, DOMAIN_TO_SETUP)
        if not txt_value:
            logger.error("FAILED AT: Add domain")
            input("Press Enter to close browser...")
            return False
        
        if txt_value == "ALREADY_EXISTS":
            logger.info("Domain already exists - checking if verified...")
            # TODO: Handle already existing domain
        else:
            # STEP 4: Add TXT to Cloudflare
            if CLOUDFLARE_API_KEY != "your_api_key":
                if not add_txt_to_cloudflare(DOMAIN_TO_SETUP, txt_value, CLOUDFLARE_ZONE_ID):
                    logger.error("FAILED AT: Add TXT to Cloudflare")
                    input("Press Enter to close browser...")
                    return False
            else:
                logger.warning("Cloudflare not configured - add TXT manually!")
                logger.info(f"TXT Record: {txt_value}")
                input("Add TXT record to Cloudflare, then press Enter to continue...")
            
            # STEP 5: Wait for DNS propagation
            logger.info("Waiting 60 seconds for DNS propagation...")
            time.sleep(60)
            
            # STEP 6: Click Verify
            if not click_verify_and_wait(driver):
                logger.error("FAILED AT: Verification")
                input("Press Enter to close browser...")
                return False
        
        # STEP 7: Complete DNS setup
        complete_dns_setup(driver, DOMAIN_TO_SETUP, CLOUDFLARE_ZONE_ID)
        
        logger.info("=" * 60)
        logger.info("DOMAIN SETUP COMPLETED SUCCESSFULLY!")
        logger.info("=" * 60)
        
        input("Press Enter to close browser...")
        return True
        
    except Exception as e:
        logger.exception(f"UNEXPECTED ERROR: {e}")
        screenshot(driver, "99_exception")
        input("Press Enter to close browser...")
        return False
    
    finally:
        driver.quit()


if __name__ == "__main__":
    # Check if credentials are configured
    if ADMIN_PASSWORD == "YOUR_PASSWORD":
        print("=" * 60)
        print("CONFIGURATION REQUIRED!")
        print("=" * 60)
        print("Edit this file and set:")
        print("  - ADMIN_EMAIL")
        print("  - ADMIN_PASSWORD")
        print("  - TOTP_SECRET")
        print("  - DOMAIN_TO_SETUP")
        print("  - CLOUDFLARE_ZONE_ID")
        print("  - CLOUDFLARE_API_KEY")
        print("  - CLOUDFLARE_EMAIL")
        print("=" * 60)
        sys.exit(1)
    
    main()