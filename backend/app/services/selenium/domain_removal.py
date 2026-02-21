"""
M365 Admin Portal - Domain Removal Automation

Removes a custom domain from an M365 tenant via Selenium.
Prerequisites: All mailboxes and UPNs using the domain must be removed first.
"""
import time
import os
import pyotp
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException
import logging

logger = logging.getLogger(__name__)
SCREENSHOT_DIR = os.environ.get("SCREENSHOT_DIR", os.path.join(os.environ.get("TEMP", os.environ.get("TMP", "/tmp")), "screenshots"))
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def screenshot(driver, step, domain=""):
    """Save a debug screenshot."""
    safe_domain = domain.replace(".", "_") if domain else "nodomain"
    path = os.path.join(SCREENSHOT_DIR, f"removal_{step}_{safe_domain}_{int(time.time())}.png")
    try:
        driver.save_screenshot(path)
        logger.info(f"Screenshot: {path}")
    except Exception as e:
        logger.warning(f"Could not save screenshot: {e}")


def create_browser(headless=True):
    """Create a Chrome browser instance."""
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    prefs = {"credentials_enable_service": False, "profile.password_manager_enabled": False}
    options.add_experimental_option("prefs", prefs)
    driver = webdriver.Chrome(options=options)
    driver.implicitly_wait(10)
    driver.set_page_load_timeout(60)
    return driver


def do_login(driver, admin_email, admin_password, totp_secret=None):
    """
    Login to M365 Admin Portal. Returns True/False.
    
    totp_secret can be None/empty if MFA is disabled on this tenant.
    """
    logger.info(f"Logging in to M365 Admin Portal as {admin_email}")
    driver.get("https://admin.microsoft.com")
    time.sleep(5)
    
    # Enter email
    try:
        email_field = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.NAME, "loginfmt"))
        )
        email_field.clear()
        email_field.send_keys(admin_email + Keys.RETURN)
        time.sleep(5)
    except TimeoutException:
        logger.error("Could not find email input field")
        return False
    
    # Enter password
    try:
        password_field = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.NAME, "passwd"))
        )
        password_field.clear()
        password_field.send_keys(admin_password + Keys.RETURN)
        time.sleep(5)
    except TimeoutException:
        logger.error("Could not find password input field")
        return False
    
    # Check for login errors
    page_source = driver.page_source.lower()
    error_indicators = [
        "password is incorrect",
        "your account or password is incorrect",
        "account doesn't exist",
        "account has been locked",
        "sign-in was blocked",
    ]
    for indicator in error_indicators:
        if indicator in page_source:
            logger.error(f"Login failed: {indicator}")
            return False
    
    # Handle TOTP if MFA is enabled AND we have a secret
    if totp_secret:
        try:
            totp_field = WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.NAME, "otc"))
            )
            code = pyotp.TOTP(totp_secret).now()
            totp_field.send_keys(code + Keys.RETURN)
            time.sleep(5)
            logger.info("TOTP code submitted")
        except TimeoutException:
            logger.debug("No TOTP field found - MFA may not be required for this tenant")
    else:
        # No TOTP secret provided - check if MFA is being prompted
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.NAME, "otc"))
            )
            logger.error("MFA required but no TOTP secret provided!")
            return False
        except TimeoutException:
            logger.debug("No MFA prompt - continuing without TOTP")
    
    # Handle "Stay signed in?"
    try:
        no_btn = WebDriverWait(driver, 8).until(
            EC.element_to_be_clickable((By.ID, "idBtn_Back"))
        )
        no_btn.click()
        time.sleep(3)
    except TimeoutException:
        pass
    
    # Verify we're in admin portal
    time.sleep(5)
    current = driver.current_url
    if "admin.microsoft.com" in current or "admin.cloud.microsoft" in current:
        logger.info(f"Login successful. URL: {current}")
        return True
    
    logger.error(f"Login may have failed. URL: {current}")
    return False


def _dismiss_popups(driver):
    """Dismiss any teaching bubbles, callouts, or overlay popups from the M365 admin portal."""
    try:
        # Temporarily disable implicit wait so we don't wait 10s per missing selector
        driver.implicitly_wait(0)
        
        # Try to find and click close/dismiss buttons on teaching bubbles
        dismiss_selectors = [
            # TeachingBubble close button
            "//div[contains(@class, 'TeachingBubble')]//button[contains(@aria-label, 'Close')]",
            "//div[contains(@class, 'TeachingBubble')]//button[contains(@aria-label, 'Dismiss')]",
            "//div[contains(@class, 'TeachingBubble')]//button[contains(@class, 'close')]",
            # Callout close buttons
            "//div[contains(@class, 'ms-Callout')]//button[contains(@aria-label, 'Close')]",
            "//div[contains(@class, 'ms-Callout')]//button[contains(@aria-label, 'Dismiss')]",
            # Generic dismiss/Got it buttons
            "//button[contains(text(), 'Got it')]",
            "//button[contains(text(), 'Dismiss')]",
            "//button[contains(text(), 'Not now')]",
            "//button[contains(text(), 'Skip')]",
        ]
        for selector in dismiss_selectors:
            try:
                btns = driver.find_elements(By.XPATH, selector)
                for btn in btns:
                    try:
                        btn.click()
                        logger.info(f"Dismissed popup via: {selector}")
                        time.sleep(0.5)
                    except Exception:
                        pass
            except Exception:
                pass
        
        # Also try removing teaching bubble overlays via JS
        driver.execute_script("""
            document.querySelectorAll('[class*="TeachingBubble"], [class*="ms-Callout"]').forEach(el => {
                el.remove();
            });
        """)
    except Exception as e:
        logger.debug(f"Popup dismissal sweep: {e}")
    finally:
        # Restore implicit wait
        driver.implicitly_wait(10)


def _handle_default_domain_panel(driver, admin_email, domain_name):
    """
    Handle the 'Set a new default before removing this domain' side panel.
    
    This panel only appears when the domain being removed is the tenant's primary/default domain.
    It requires selecting a new default domain (the onmicrosoft.com domain) from a dropdown
    before the removal can proceed.
    """
    try:
        driver.implicitly_wait(2)
        
        # Check if the "Set a new default" panel appeared
        panel_indicators = [
            "//*[contains(text(), 'Set a new default')]",
            "//*[contains(text(), 'new default domain')]",
            "//*[contains(text(), 'currently your default')]",
        ]
        
        panel_found = False
        for indicator in panel_indicators:
            try:
                driver.find_element(By.XPATH, indicator)
                panel_found = True
                break
            except NoSuchElementException:
                continue
        
        if not panel_found:
            logger.debug("No default domain panel detected - domain is not the primary")
            return
        
        logger.info(f"[{domain_name}] Default domain panel detected - need to select new default")
        screenshot(driver, "04a_default_panel", domain_name)
        
        # Extract the onmicrosoft domain from admin_email (e.g., wassim@wassim615.onmicrosoft.com -> wassim615.onmicrosoft.com)
        onmicrosoft_domain = None
        if "@" in admin_email and "onmicrosoft.com" in admin_email:
            onmicrosoft_domain = admin_email.split("@")[1]
            logger.info(f"Will select onmicrosoft domain: {onmicrosoft_domain}")
        
        # Click the dropdown to open it
        dropdown_clicked = False
        dropdown_selectors = [
            "//*[contains(text(), 'Select a domain')]",
            "//div[contains(@class, 'ms-Dropdown')]",
            "//div[contains(@role, 'combobox')]",
            "//div[contains(@role, 'listbox')]",
            "//button[contains(@aria-haspopup, 'listbox')]",
            "//*[contains(@class, 'dropdown')]//button",
            "//*[contains(@class, 'Dropdown')]",
        ]
        
        for sel in dropdown_selectors:
            try:
                dropdown = driver.find_element(By.XPATH, sel)
                try:
                    dropdown.click()
                except ElementClickInterceptedException:
                    driver.execute_script("arguments[0].click()", dropdown)
                dropdown_clicked = True
                logger.info(f"Clicked dropdown via: {sel}")
                time.sleep(2)
                break
            except NoSuchElementException:
                continue
        
        if not dropdown_clicked:
            logger.warning("Could not find dropdown, trying to click any combobox-like element")
            # Try JS approach to find and click dropdown
            driver.execute_script("""
                var dropdowns = document.querySelectorAll('[role="combobox"], [role="listbox"], [class*="Dropdown"], [class*="dropdown"]');
                if (dropdowns.length > 0) dropdowns[0].click();
            """)
            time.sleep(2)
        
        screenshot(driver, "04b_dropdown_opened", domain_name)
        
        # Select the onmicrosoft.com option from the dropdown
        # IMPORTANT: We must be careful not to click the panel description text
        # which also contains "onmicrosoft.com". We need to target only dropdown options.
        option_selected = False
        
        # Strategy 1: Target elements with role="option" containing onmicrosoft
        role_option_selectors = [
            "//*[@role='option'][contains(., 'onmicrosoft')]",
            "//*[@role='option'][contains(text(), 'onmicrosoft')]",
        ]
        for sel in role_option_selectors:
            try:
                options = driver.find_elements(By.XPATH, sel)
                for opt in options:
                    try:
                        opt.click()
                    except ElementClickInterceptedException:
                        driver.execute_script("arguments[0].click()", opt)
                    option_selected = True
                    logger.info(f"Selected onmicrosoft option via role='option': {sel}")
                    time.sleep(2)
                    break
                if option_selected:
                    break
            except Exception:
                continue
        
        # Strategy 2: Target elements inside a listbox or dropdown container
        if not option_selected:
            container_selectors = [
                "//*[@role='listbox']//*[contains(text(), 'onmicrosoft')]",
                "//*[contains(@class, 'Dropdown')]//*[contains(text(), 'onmicrosoft')]",
                "//*[contains(@class, 'dropdown')]//*[contains(text(), 'onmicrosoft')]",
                "//*[contains(@class, 'dropdownItem')][contains(., 'onmicrosoft')]",
                "//*[contains(@class, 'DropdownItem')][contains(., 'onmicrosoft')]",
                "//*[contains(@class, 'ms-Dropdown-item')][contains(., 'onmicrosoft')]",
            ]
            for sel in container_selectors:
                try:
                    options = driver.find_elements(By.XPATH, sel)
                    for opt in options:
                        try:
                            opt.click()
                        except ElementClickInterceptedException:
                            driver.execute_script("arguments[0].click()", opt)
                        option_selected = True
                        logger.info(f"Selected onmicrosoft option via container: {sel}")
                        time.sleep(2)
                        break
                    if option_selected:
                        break
                except Exception:
                    continue
        
        # Strategy 3: Use find_elements to get ALL onmicrosoft text matches, skip description text
        if not option_selected:
            search_text = onmicrosoft_domain if onmicrosoft_domain else "onmicrosoft.com"
            all_matches = driver.find_elements(By.XPATH, f"//*[contains(text(), '{search_text}')]")
            logger.info(f"Found {len(all_matches)} elements containing '{search_text}'")
            
            for match in all_matches:
                tag = match.tag_name.lower()
                text = match.text.strip()
                parent_role = ""
                try:
                    parent_role = match.find_element(By.XPATH, "..").get_attribute("role") or ""
                except Exception:
                    pass
                
                # Skip elements that look like description/header text (long text, paragraph-like)
                if len(text) > 80:
                    logger.debug(f"Skipping long text element: {text[:60]}...")
                    continue
                
                # Skip if the text contains "currently" (part of the description)
                if "currently" in text.lower():
                    logger.debug(f"Skipping description element: {text[:60]}...")
                    continue
                
                # Prefer button, span, div, li elements that are short text (likely dropdown items)
                if tag in ("button", "span", "div", "li", "option") and search_text in text:
                    logger.info(f"Trying dropdown option: tag={tag}, text='{text}', parent_role={parent_role}")
                    try:
                        match.click()
                    except ElementClickInterceptedException:
                        driver.execute_script("arguments[0].click()", match)
                    option_selected = True
                    logger.info(f"Selected onmicrosoft option via text scan: '{text}'")
                    time.sleep(2)
                    break
        
        # Strategy 4: JS fallback - try multiple selectors
        if not option_selected:
            logger.warning("Could not select onmicrosoft.com option via Selenium - trying JS")
            result = driver.execute_script("""
                // Try role="option" first
                var options = document.querySelectorAll('[role="option"]');
                for (var i = 0; i < options.length; i++) {
                    if (options[i].textContent.includes('onmicrosoft')) {
                        options[i].click();
                        return 'clicked role=option';
                    }
                }
                // Try dropdown item classes
                var items = document.querySelectorAll('[class*="dropdownItem"], [class*="DropdownItem"], [class*="ms-Dropdown-item"], [class*="listbox"] *');
                for (var i = 0; i < items.length; i++) {
                    if (items[i].textContent.includes('onmicrosoft') && items[i].textContent.length < 80) {
                        items[i].click();
                        return 'clicked dropdown item';
                    }
                }
                // Last resort: find all elements, skip description text
                var all = document.querySelectorAll('button, span, div, li, option');
                for (var i = 0; i < all.length; i++) {
                    var txt = all[i].textContent.trim();
                    if (txt.includes('onmicrosoft') && txt.length < 80 && !txt.includes('currently')) {
                        all[i].click();
                        return 'clicked generic element: ' + txt.substring(0, 50);
                    }
                }
                return 'no match found';
            """)
            logger.info(f"JS fallback result: {result}")
            if result and 'clicked' in str(result):
                option_selected = True
            time.sleep(2)
        
        screenshot(driver, "04c_option_selected", domain_name)
        
        # Now click the save/confirm/set default button to proceed
        save_selectors = [
            "//button[contains(text(), 'Update and continue')]",
            "//button[contains(text(), 'Update')]",
            "//button[contains(text(), 'Set as default')]",
            "//button[contains(text(), 'Save')]",
            "//button[contains(text(), 'Confirm')]",
            "//button[contains(text(), 'Continue')]",
            "//button[contains(text(), 'OK')]",
            # Also try span inside button (Fluent UI pattern)
            "//button[.//span[contains(text(), 'Update and continue')]]",
            "//button[.//span[contains(text(), 'Update')]]",
            # Any clickable element with that text
            "//*[contains(text(), 'Update and continue')]",
        ]
        
        save_clicked = False
        for sel in save_selectors:
            try:
                save_btn = driver.find_element(By.XPATH, sel)
                # Check if the button is enabled before clicking
                is_disabled = save_btn.get_attribute("disabled")
                aria_disabled = save_btn.get_attribute("aria-disabled")
                if is_disabled == "true" or aria_disabled == "true":
                    logger.info(f"Found button via {sel} but it's disabled - option may not be selected yet")
                    continue
                try:
                    save_btn.click()
                except ElementClickInterceptedException:
                    driver.execute_script("arguments[0].click()", save_btn)
                save_clicked = True
                logger.info(f"Clicked save/confirm via: {sel}")
                time.sleep(5)
                break
            except NoSuchElementException:
                continue
        
        # If button was disabled (option not selected), wait and retry
        if not save_clicked:
            logger.warning("Save button not clicked (may be disabled). Waiting and retrying...")
            time.sleep(3)
            screenshot(driver, "04c2_retry_save", domain_name)
            for sel in save_selectors:
                try:
                    save_btn = driver.find_element(By.XPATH, sel)
                    try:
                        save_btn.click()
                    except ElementClickInterceptedException:
                        driver.execute_script("arguments[0].click()", save_btn)
                    save_clicked = True
                    logger.info(f"Retry: clicked save/confirm via: {sel}")
                    time.sleep(5)
                    break
                except NoSuchElementException:
                    continue
        
        screenshot(driver, "04d_default_set", domain_name)
        logger.info(f"[{domain_name}] Default domain panel handled successfully")
        
    except Exception as e:
        logger.warning(f"Error handling default domain panel: {e}")
        screenshot(driver, "04e_default_panel_error", domain_name)
    finally:
        driver.implicitly_wait(10)


def remove_domain_from_m365(
    domain_name: str,
    admin_email: str,
    admin_password: str,
    totp_secret: str = None,
    headless: bool = True
) -> dict:
    """
    Remove a custom domain from M365 tenant via Admin Portal.
    
    PREREQUISITE: All mailboxes/UPNs using this domain must already be removed.
    totp_secret: Can be None/empty if MFA is disabled on this tenant.
    
    Returns: {"success": bool, "error": str|None}
    """
    driver = None
    try:
        driver = create_browser(headless=headless)
        
        # Login
        if not do_login(driver, admin_email, admin_password, totp_secret):
            screenshot(driver, "login_failed", domain_name)
            return {"success": False, "error": "Login failed - check credentials or MFA"}
        
        screenshot(driver, "01_logged_in", domain_name)
        
        # Navigate to Domains page
        domains_url = "https://admin.cloud.microsoft/#/Domains"
        logger.info(f"Navigating to domains page: {domains_url}")
        driver.get(domains_url)
        time.sleep(8)
        screenshot(driver, "02_domains_page", domain_name)
        
        # Dismiss any teaching bubbles / popups that overlay the page
        _dismiss_popups(driver)
        
        # Find and click on the domain
        domain_found = False
        max_attempts = 3
        
        for attempt in range(max_attempts):
            try:
                domain_link = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((
                        By.XPATH, 
                        f"//span[contains(text(), '{domain_name}')] | "
                        f"//a[contains(text(), '{domain_name}')] | "
                        f"//div[contains(text(), '{domain_name}')]"
                    ))
                )
                try:
                    domain_link.click()
                except ElementClickInterceptedException:
                    logger.warning("Click intercepted by overlay, dismissing popups and using JS click")
                    _dismiss_popups(driver)
                    time.sleep(1)
                    driver.execute_script("arguments[0].click()", domain_link)
                domain_found = True
                time.sleep(3)
                break
            except TimeoutException:
                logger.warning(f"Attempt {attempt+1}: Domain '{domain_name}' not found in list")
                _dismiss_popups(driver)
                time.sleep(2)
        
        if not domain_found:
            screenshot(driver, "03_domain_not_found", domain_name)
            # If the domain is not in the tenant's domain list, it's already removed — that's a success!
            logger.info(f"Domain '{domain_name}' not found in tenant domain list - treating as already removed")
            return {"success": True, "error": None, "note": "Domain not found in tenant - already removed or never added"}
        
        screenshot(driver, "03_domain_selected", domain_name)
        
        # Look for "Remove domain" or "Delete domain" link/button
        # On the new admin portal, this is often a span/link with role="button", not a <button>
        _dismiss_popups(driver)
        remove_clicked = False
        remove_selectors = [
            # Direct text match on any element
            "//*[contains(text(), 'Remove domain')]",
            "//*[contains(text(), 'Delete domain')]",
            # Button elements
            "//button[contains(text(), 'Remove')]",
            "//button[contains(text(), 'Delete')]",
            # Span with role=button
            "//span[contains(text(), 'Remove domain')]",
            "//span[contains(text(), 'Remove') and @role='button']",
            # Aria-label
            "//*[contains(@aria-label, 'Remove domain')]",
            "//*[contains(@aria-label, 'Delete domain')]",
        ]
        
        # Temporarily lower implicit wait for fast selector scanning
        driver.implicitly_wait(1)
        for sel in remove_selectors:
            try:
                remove_btn = WebDriverWait(driver, 2).until(
                    EC.presence_of_element_located((By.XPATH, sel))
                )
                logger.info(f"Found remove button via: {sel}")
                try:
                    remove_btn.click()
                except ElementClickInterceptedException:
                    _dismiss_popups(driver)
                    driver.execute_script("arguments[0].click()", remove_btn)
                remove_clicked = True
                time.sleep(3)
                break
            except TimeoutException:
                continue
        driver.implicitly_wait(10)
        
        if not remove_clicked:
            screenshot(driver, "04_no_remove_btn", domain_name)
            # Try the three-dot menu / more actions as last resort
            try:
                more_btn = driver.find_element(
                    By.XPATH, 
                    "//button[contains(@aria-label, 'More')] | "
                    "//button[contains(@aria-label, 'Actions')] | "
                    "//i[contains(@class, 'MoreVertical')]/parent::button"
                )
                more_btn.click()
                time.sleep(2)
                
                remove_option = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((
                        By.XPATH,
                        "//*[contains(text(), 'Remove')]"
                    ))
                )
                try:
                    remove_option.click()
                except ElementClickInterceptedException:
                    driver.execute_script("arguments[0].click()", remove_option)
                remove_clicked = True
                time.sleep(3)
            except Exception:
                screenshot(driver, "04_cannot_find_remove", domain_name)
                return {"success": False, "error": "Could not find Remove Domain button - domain may have active resources still assigned"}
        
        if not remove_clicked:
            return {"success": False, "error": "Could not click Remove Domain button"}
        
        screenshot(driver, "04_remove_clicked", domain_name)
        
        # Handle "Set a new default domain" panel (only appears when removing the primary/default domain)
        _handle_default_domain_panel(driver, admin_email, domain_name)
        
        # Confirm removal dialog - handle "Automatically remove" button and similar
        # Fluent UI renders button text inside nested <span>, so use "." (descendant text) not "text()"
        confirm_clicked = False
        confirm_selectors = [
            # Exact match for "Automatically remove" (the new M365 admin portal button)
            "//button[contains(., 'Automatically remove')]",
            "//*[contains(text(), 'Automatically remove')]",
            # General remove/delete/confirm buttons using descendant text matching
            "//button[contains(., 'Remove domain')]",
            "//button[contains(., 'Remove')]",
            "//button[contains(., 'Delete')]",
            "//button[contains(., 'Confirm')]",
            "//button[contains(., 'Yes')]",
            # Fallback: direct text() match
            "//button[contains(text(), 'Remove')]",
            "//button[contains(text(), 'Delete')]",
            "//button[contains(text(), 'Confirm')]",
        ]
        
        driver.implicitly_wait(2)
        for sel in confirm_selectors:
            try:
                confirm_btn = WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((By.XPATH, sel))
                )
                logger.info(f"Found confirm button via: {sel}")
                try:
                    confirm_btn.click()
                except ElementClickInterceptedException:
                    driver.execute_script("arguments[0].click()", confirm_btn)
                confirm_clicked = True
                logger.info(f"Clicked confirm removal via: {sel}")
                time.sleep(5)
                break
            except TimeoutException:
                continue
        driver.implicitly_wait(10)
        
        if not confirm_clicked:
            # JS fallback for the confirm button
            result = driver.execute_script("""
                var buttons = document.querySelectorAll('button');
                for (var i = 0; i < buttons.length; i++) {
                    var txt = buttons[i].textContent.trim();
                    if (txt.includes('Automatically remove') || txt.includes('Remove domain')) {
                        buttons[i].click();
                        return 'clicked: ' + txt;
                    }
                }
                // Second pass: any button with "Remove"
                for (var i = 0; i < buttons.length; i++) {
                    var txt = buttons[i].textContent.trim();
                    if (txt.includes('Remove') && !txt.includes('How to')) {
                        buttons[i].click();
                        return 'clicked: ' + txt;
                    }
                }
                return 'no confirm button found';
            """)
            logger.info(f"JS confirm fallback result: {result}")
            if result and 'clicked' in str(result):
                confirm_clicked = True
            time.sleep(5)
        
        if not confirm_clicked:
            logger.warning("No confirmation button found, removal may have proceeded directly")
        
        screenshot(driver, "05_removal_confirmed", domain_name)
        
        # Wait for removal to process — M365 "Automatically remove" is async and can take 15-30+ seconds
        logger.info(f"Waiting for M365 to process domain removal for '{domain_name}'...")
        time.sleep(20)
        screenshot(driver, "06_after_removal", domain_name)
        
        # Check current page for success indicators
        page_source = driver.page_source.lower()
        success_indicators = [
            "has been removed",
            "successfully removed",
            "domain was removed",
            "removal complete",
            "successfully",
            "removed from your organization",
            "no longer available",
        ]
        for indicator in success_indicators:
            if indicator in page_source:
                logger.info(f"Domain '{domain_name}' removed successfully (confirmed by page text: '{indicator}')")
                return {"success": True, "error": None}
        
        # Check if we're back on the domains list (removal redirected us) and domain is gone
        if "/Domains" in driver.current_url and domain_name not in page_source:
            logger.info(f"Domain '{domain_name}' removed successfully (no longer on current page)")
            return {"success": True, "error": None}
        
        # Navigate to domains list and check — retry up to 4 times with waits
        # because M365 removal is async and can take time to disappear from the list
        max_verify_attempts = 4
        for verify_attempt in range(max_verify_attempts):
            try:
                driver.get("https://admin.cloud.microsoft/#/Domains")
                wait_time = 15 + (verify_attempt * 10)  # 15s, 25s, 35s, 45s
                logger.info(f"Verify attempt {verify_attempt + 1}/{max_verify_attempts}: waiting {wait_time}s for domains list to load...")
                time.sleep(wait_time)
                
                driver.implicitly_wait(3)
                try:
                    driver.find_element(By.XPATH, f"//span[contains(text(), '{domain_name}')]")
                    driver.implicitly_wait(10)
                    
                    if verify_attempt < max_verify_attempts - 1:
                        logger.info(f"Domain still in list on attempt {verify_attempt + 1}, waiting longer...")
                        continue
                    else:
                        screenshot(driver, "07_domain_still_present", domain_name)
                        # Domain is STILL in the list after all verification attempts
                        # Do NOT treat as success — the domain was not actually removed
                        logger.warning(f"Domain '{domain_name}' still in tenant domain list after {max_verify_attempts} verification attempts — removal FAILED")
                        return {
                            "success": False,
                            "error": f"Domain still present in tenant after removal attempt and {max_verify_attempts} verification checks",
                            "confirm_button_clicked": confirm_clicked,
                            "needs_retry": True
                        }
                except NoSuchElementException:
                    driver.implicitly_wait(10)
                    logger.info(f"Domain '{domain_name}' confirmed removed (not in domain list on attempt {verify_attempt + 1})")
                    return {"success": True, "error": None}
            except Exception as e:
                driver.implicitly_wait(10)
                logger.warning(f"Error during verification attempt {verify_attempt + 1}: {e}")
                if verify_attempt == max_verify_attempts - 1:
                    # Could not load the verification page — we cannot confirm removal
                    logger.error(f"Could not verify removal of '{domain_name}' — treating as FAILED to be safe")
                    return {
                        "success": False,
                        "error": f"Could not verify removal (page load failed): {e}",
                        "confirm_button_clicked": confirm_clicked,
                        "needs_retry": True
                    }
        
        # Should not reach here, but just in case — never assume success without confirmation
        logger.error(f"Domain '{domain_name}' removal could not be confirmed — treating as FAILED")
        return {
            "success": False,
            "error": "Removal could not be confirmed after all attempts",
            "confirm_button_clicked": confirm_clicked,
            "needs_retry": True
        }
        
    except Exception as e:
        logger.exception(f"Error removing domain '{domain_name}': {e}")
        if driver:
            screenshot(driver, "error", domain_name)
        return {"success": False, "error": str(e)}
    
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
