"""
Step 5 Phases — Individual phases for M365 domain setup.

Phase 1: Login
Phase 2: Add Domain + TXT extraction
Phase 3: Verify Domain
Phase 4: DNS Records (MX, SPF, Autodiscover)
Phase 5A: DKIM CNAMEs
Phase 5B: DKIM Enable
"""

import time
import re
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from app.services.selenium.step5_helpers import (
    dismiss_popups, safe_click, find_and_click, wait_for_text,
    get_fresh_totp, detect_page_state, save_screenshot,
    PHASE_RETRIES, DNS_WAIT, DKIM_WAIT, VERIFY_RETRY_WAIT,
)

logger = logging.getLogger(__name__)


# ============================================================
# PHASE 1: LOGIN
# ============================================================

def phase_login(driver, admin_email, admin_password, totp_secret, domain):
    """Login to M365 Admin Portal. Retries PHASE_RETRIES times."""
    for attempt in range(1, PHASE_RETRIES + 1):
        try:
            logger.info(f"[{domain}] LOGIN attempt {attempt}/{PHASE_RETRIES}")

            # Navigate — wrapped with explicit logging
            logger.info(f"[{domain}] Navigating to admin.microsoft.com...")
            try:
                driver.get("https://admin.microsoft.com")
                logger.info(f"[{domain}] Navigation complete, URL: {driver.current_url}")
            except Exception as nav_err:
                logger.error(f"[{domain}] Navigation FAILED: {nav_err}")
                try:
                    save_screenshot(driver, domain, f"nav_failed_a{attempt}")
                except Exception:
                    pass
                continue

            time.sleep(4)
            logger.info(f"[{domain}] After wait, URL: {driver.current_url}")

            # Check page loaded
            try:
                page_text_preview = driver.find_element(By.TAG_NAME, "body").text[:200]
                logger.info(f"[{domain}] Page text preview: {page_text_preview}")
            except Exception as e:
                logger.warning(f"[{domain}] Cannot read page body: {e}")

            dismiss_popups(driver)
            save_screenshot(driver, domain, f"login_start_a{attempt}")

            # --- ACCOUNT PICKER ---
            try:
                page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
                if "pick an account" in page_text or "choose an account" in page_text:
                    logger.info(f"[{domain}] Account picker detected")
                    try:
                        acct = driver.find_element(By.XPATH, f"//*[contains(text(), '{admin_email}')]")
                        safe_click(driver, acct, "account in picker", domain)
                        time.sleep(3)
                    except Exception:
                        find_and_click(driver, [
                            (By.XPATH, "//*[contains(text(), 'Use another account')]"),
                            (By.XPATH, "//*[contains(text(), 'use a different account')]"),
                        ], "use another account", domain)
                        time.sleep(2)
            except Exception as e:
                logger.warning(f"[{domain}] Account picker handling: {e}")

            # --- EMAIL ---
            try:
                email_input = WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((
                        By.CSS_SELECTOR, "input[type='email'], input[name='loginfmt']"
                    ))
                )
                email_input.clear()
                time.sleep(0.3)
                email_input.send_keys(admin_email)
                time.sleep(0.5)
                email_input.send_keys(Keys.ENTER)
                logger.info(f"[{domain}] Entered email")
                time.sleep(3)
            except TimeoutException:
                logger.info(f"[{domain}] No email input found, may already be past this step")

            # --- PASSWORD ---
            try:
                pwd_input = WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((
                        By.CSS_SELECTOR, "input[type='password'], input[name='passwd']"
                    ))
                )
                pwd_input.clear()
                time.sleep(0.3)
                pwd_input.send_keys(admin_password)
                time.sleep(0.5)
                pwd_input.send_keys(Keys.ENTER)
                logger.info(f"[{domain}] Entered password")
                time.sleep(4)
            except TimeoutException:
                logger.info(f"[{domain}] No password input found")

            # --- HANDLE ACTION REQUIRED / SECURITY DEFAULTS ---
            try:
                page_text = driver.page_source.lower()
                if any(x in page_text for x in ["action required", "more information required", "keep your account secure"]):
                    logger.info(f"[{domain}] Action required flow detected, clicking Next")
                    find_and_click(driver, [
                        (By.ID, "idSubmit_ProofUp_Redirect"),
                        (By.ID, "idSIButton9"),
                        (By.XPATH, "//button[contains(text(), 'Next')]"),
                    ], "Action Required Next", domain, timeout=5)
                    time.sleep(3)
            except Exception as e:
                logger.warning(f"[{domain}] Action required handling: {e}")

            # --- MFA / TOTP ---
            try:
                totp_selectors = [
                    (By.ID, "idTxtBx_SAOTC_OTC"),
                    (By.ID, "idTxtBx_SAOTCC_OTC"),
                    (By.NAME, "otc"),
                    (By.CSS_SELECTOR, "input[type='tel']"),
                    (By.CSS_SELECTOR, "input[aria-label*='code']"),
                    (By.CSS_SELECTOR, "input[maxlength='6']"),
                ]
                totp_input = None
                for sel_type, sel_val in totp_selectors:
                    try:
                        totp_input = WebDriverWait(driver, 8).until(
                            EC.presence_of_element_located((sel_type, sel_val))
                        )
                        break
                    except TimeoutException:
                        continue

                if totp_input:
                    logger.info(f"[{domain}] MFA detected")
                    code = get_fresh_totp(totp_secret)
                    totp_input.clear()
                    time.sleep(0.3)
                    totp_input.send_keys(code)
                    time.sleep(0.5)
                    find_and_click(driver, [
                        (By.ID, "idSubmit_SAOTC_Continue"),
                        (By.ID, "idSubmit_SAOTCC_Continue"),
                        (By.CSS_SELECTOR, "input[type='submit']"),
                        (By.CSS_SELECTOR, "button[type='submit']"),
                    ], "MFA verify button", domain)
                    time.sleep(4)
                    logger.info(f"[{domain}] MFA submitted")
                else:
                    logger.info(f"[{domain}] No MFA prompt")
            except Exception as e:
                logger.warning(f"[{domain}] MFA handling: {e}")

            # --- STAY SIGNED IN ---
            try:
                find_and_click(driver, [
                    (By.ID, "idSIButton9"),
                    (By.ID, "idBtn_Back"),
                    (By.CSS_SELECTOR, "input[value='Yes']"),
                    (By.XPATH, "//button[contains(text(), 'Yes')]"),
                ], "Stay signed in - Yes", domain, timeout=8)
                time.sleep(3)
            except Exception as e:
                logger.info(f"[{domain}] Stay signed in prompt not found (OK): {e}")

            # --- VERIFY LOGGED IN ---
            time.sleep(3)
            url = driver.current_url.lower()
            if "admin.microsoft.com" in url or "portal" in url or "microsoft" in url:
                logger.info(f"[{domain}] LOGIN successful")
                save_screenshot(driver, domain, "login_success")
                return True
            else:
                logger.warning(f"[{domain}] Unexpected URL after login: {url}")
                save_screenshot(driver, domain, "login_unexpected_url")
                return True  # Try to proceed anyway

        except Exception as e:
            logger.error(f"[{domain}] Login attempt {attempt} failed: {e}")
            save_screenshot(driver, domain, f"login_fail_a{attempt}")
            if attempt < PHASE_RETRIES:
                time.sleep(10)

    logger.error(f"[{domain}] LOGIN FAILED after {PHASE_RETRIES} attempts")
    return False


# ============================================================
# PHASE 2: ADD DOMAIN
# ============================================================

def phase_add_domain(driver, domain):
    """Add domain to M365. Returns dict with success, txt_value, already_verified."""
    for attempt in range(1, PHASE_RETRIES + 1):
        try:
            logger.info(f"[{domain}] ADD DOMAIN attempt {attempt}/{PHASE_RETRIES}")
            driver.get("https://admin.microsoft.com/Adminportal/Home#/Domains")
            time.sleep(5)
            dismiss_popups(driver)
            save_screenshot(driver, domain, f"domains_page_a{attempt}")

            # Check if domain already exists
            try:
                existing = driver.find_elements(By.XPATH, f"//*[contains(text(), '{domain}')]")
                if existing:
                    logger.info(f"[{domain}] Domain already exists in M365")
                    safe_click(driver, existing[0], f"existing domain {domain}", domain)
                    time.sleep(3)
                    state = detect_page_state(driver, domain)
                    if state in ("complete", "connect_domain"):
                        return {"success": True, "txt_value": None, "already_verified": True}
                    elif state == "verification":
                        txt = _extract_txt_value(driver, domain)
                        return {"success": bool(txt), "txt_value": txt, "already_verified": False}
                    return {"success": True, "txt_value": None, "already_verified": True}
            except Exception:
                pass

            # Click "Add domain"
            clicked = find_and_click(driver, [
                (By.XPATH, "//button[contains(text(), 'Add domain')]"),
                (By.XPATH, "//span[contains(text(), 'Add domain')]/ancestor::button"),
                (By.XPATH, "//button[contains(@aria-label, 'Add domain')]"),
            ], "Add domain button", domain)

            if not clicked:
                # Fallback: navigate directly to wizard
                logger.info(f"[{domain}] Navigating directly to wizard")
                driver.get("https://admin.microsoft.com/#/Domains/Wizard")
                time.sleep(5)

            time.sleep(3)

            # Enter domain name
            try:
                domain_input = WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text']"))
                )
                domain_input.clear()
                time.sleep(0.3)
                domain_input.send_keys(domain)
                time.sleep(0.5)
                logger.info(f"[{domain}] Entered domain name")
            except Exception as e:
                logger.error(f"[{domain}] Could not enter domain name: {e}")
                save_screenshot(driver, domain, "domain_input_fail")
                continue

            # Click "Use this domain" / "Next"
            find_and_click(driver, [
                (By.XPATH, "//button[contains(text(), 'Use this domain')]"),
                (By.XPATH, "//button[contains(text(), 'Add domain')]"),
                (By.XPATH, "//button[contains(text(), 'Next')]"),
                (By.CSS_SELECTOR, "button[type='submit']"),
            ], "Use this domain button", domain)
            time.sleep(5)

            # Detect page state
            state = detect_page_state(driver, domain)
            logger.info(f"[{domain}] Page state after domain entry: {state}")

            if state == "already_exists":
                return {"success": True, "txt_value": None, "already_verified": True}
            if state in ("connect_domain", "complete"):
                return {"success": True, "txt_value": None, "already_verified": True}

            if state == "verification":
                # Click "More options" to show TXT option
                find_and_click(driver, [
                    (By.XPATH, "//*[contains(text(), 'More options')]"),
                ], "More options", domain, timeout=5)
                time.sleep(2)

                # Select TXT record option
                for xpath in [
                    "//input[@type='radio'][following-sibling::*[contains(text(), 'TXT record')]]",
                    "//input[@type='radio'][..//*[contains(text(), 'TXT record')]]",
                    "//*[contains(text(), 'Add a TXT record')]",
                    "//label[contains(., 'TXT record')]",
                ]:
                    try:
                        el = driver.find_element(By.XPATH, xpath)
                        driver.execute_script("arguments[0].click();", el)
                        logger.info(f"[{domain}] Selected TXT record option")
                        break
                    except Exception:
                        continue
                time.sleep(2)

                # Click Continue to see TXT value
                find_and_click(driver, [
                    (By.XPATH, "//button[contains(text(), 'Continue')]"),
                    (By.XPATH, "//button[contains(text(), 'Next')]"),
                ], "Continue to TXT value", domain, timeout=5)
                time.sleep(3)

                # Extract TXT value
                txt = _extract_txt_value(driver, domain)
                if txt:
                    return {"success": True, "txt_value": txt, "already_verified": False}
                else:
                    logger.warning(f"[{domain}] TXT extraction failed on attempt {attempt}")
                    save_screenshot(driver, domain, f"txt_extraction_fail_a{attempt}")
                    continue

            logger.warning(f"[{domain}] Unexpected state: {state}")
            save_screenshot(driver, domain, f"unexpected_state_{state}_a{attempt}")
            continue

        except Exception as e:
            logger.error(f"[{domain}] Add domain attempt {attempt} error: {e}")
            save_screenshot(driver, domain, f"add_domain_error_a{attempt}")

    return {"success": False, "txt_value": None, "already_verified": False}


def _extract_txt_value(driver, domain):
    """Extract MS= TXT verification value using 5 strategies."""
    # Strategy 1: Elements containing "MS="
    try:
        elements = driver.find_elements(By.XPATH, "//*[contains(text(), 'MS=')]")
        for el in elements:
            match = re.search(r'MS=\w{8,50}', el.text)
            if match:
                logger.info(f"[{domain}] TXT via element text: {match.group(0)}")
                return match.group(0)
    except Exception:
        pass

    # Strategy 2: Input fields
    try:
        for inp in driver.find_elements(By.TAG_NAME, "input"):
            val = inp.get_attribute("value") or ""
            match = re.search(r'MS=\w+', val)
            if match:
                logger.info(f"[{domain}] TXT via input value: {match.group(0)}")
                return match.group(0)
    except Exception:
        pass

    # Strategy 3: Page source regex
    try:
        matches = re.findall(r'MS=\w{8,50}', driver.page_source)
        if matches:
            logger.info(f"[{domain}] TXT via page source: {matches[0]}")
            return matches[0]
    except Exception:
        pass

    # Strategy 4: Table cells
    try:
        for cell in driver.find_elements(By.TAG_NAME, "td"):
            match = re.search(r'MS=\w+', cell.text or "")
            if match:
                logger.info(f"[{domain}] TXT via table cell: {match.group(0)}")
                return match.group(0)
    except Exception:
        pass

    # Strategy 5: Copy button siblings
    try:
        for btn in driver.find_elements(By.XPATH, "//button[contains(@aria-label, 'opy')]"):
            parent = btn.find_element(By.XPATH, "./..")
            match = re.search(r'MS=\w+', parent.text or "")
            if match:
                logger.info(f"[{domain}] TXT via copy button: {match.group(0)}")
                return match.group(0)
    except Exception:
        pass

    # Strategy 6: ms-prefixed match (broader)
    try:
        match = re.search(r'MS=ms\d+', driver.find_element(By.TAG_NAME, "body").text)
        if match:
            logger.info(f"[{domain}] TXT via body text: {match.group(0)}")
            return match.group(0)
    except Exception:
        pass

    logger.error(f"[{domain}] TXT extraction failed (all strategies)")
    save_screenshot(driver, domain, "txt_extraction_all_failed")
    return None


# ============================================================
# PHASE 3: VERIFY DOMAIN
# ============================================================

def phase_verify_domain(driver, domain):
    """Click Verify and confirm domain ownership. Retries up to 5 times."""
    MAX_VERIFY_ATTEMPTS = 5

    for attempt in range(1, MAX_VERIFY_ATTEMPTS + 1):
        logger.info(f"[{domain}] VERIFY attempt {attempt}/{MAX_VERIFY_ATTEMPTS}")
        dismiss_popups(driver)

        clicked = find_and_click(driver, [
            (By.XPATH, "//button[contains(text(), 'Verify')]"),
            (By.XPATH, "//button[contains(@aria-label, 'Verify')]"),
            (By.XPATH, "//span[contains(text(), 'Verify')]/ancestor::button"),
        ], "Verify button", domain)

        if not clicked:
            # Navigate back to domain and try again
            driver.get("https://admin.microsoft.com/Adminportal/Home#/Domains")
            time.sleep(5)
            dismiss_popups(driver)
            try:
                link = driver.find_element(By.XPATH, f"//*[contains(text(), '{domain}')]")
                safe_click(driver, link, f"domain link {domain}", domain)
                time.sleep(3)
                dismiss_popups(driver)
                find_and_click(driver, [
                    (By.XPATH, "//button[contains(text(), 'Verify')]"),
                    (By.XPATH, "//button[contains(text(), 'Continue setup')]"),
                    (By.XPATH, "//button[contains(text(), 'Finish setup')]"),
                ], "Verify/Continue button", domain)
            except Exception:
                pass

        time.sleep(10)

        state = detect_page_state(driver, domain)
        logger.info(f"[{domain}] Post-verify state: {state}")

        if state in ("complete", "connect_domain", "dns_records"):
            logger.info(f"[{domain}] Domain VERIFIED")
            return True

        if state == "dns_not_propagated":
            wait_time = DNS_WAIT + (30 * attempt)
            logger.info(f"[{domain}] DNS not propagated yet, waiting {wait_time}s...")
            time.sleep(wait_time)
            continue

        if state == "verification":
            wait_time = VERIFY_RETRY_WAIT * attempt
            logger.info(f"[{domain}] Still on verification page, waiting {wait_time}s...")
            time.sleep(wait_time)
            continue

        # Check for success text
        try:
            page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
            if "verified" in page_text or "success" in page_text:
                logger.info(f"[{domain}] Verified (text match)")
                return True
        except Exception:
            pass

        logger.warning(f"[{domain}] Verify attempt {attempt} inconclusive, state={state}")
        save_screenshot(driver, domain, f"verify_inconclusive_a{attempt}")
        if attempt < MAX_VERIFY_ATTEMPTS:
            time.sleep(30)

    logger.error(f"[{domain}] VERIFICATION FAILED after {MAX_VERIFY_ATTEMPTS} attempts")
    return False


# ============================================================
# PHASE 4: DNS RECORDS
# ============================================================

def phase_dns_records(driver, domain, zone_id):
    """Add MX, SPF, and Autodiscover records to Cloudflare."""
    from app.services.cloudflare_sync import add_mx, add_spf, add_cname

    result = {"success": False, "mx_value": None, "spf_value": None}

    try:
        page_text = driver.find_element(By.TAG_NAME, "body").text
        mx_match = re.search(r'([a-zA-Z0-9-]+\.mail\.protection\.outlook\.com)', page_text)
        spf_match = re.search(r'(v=spf1[^\n"<>]+)', page_text)

        mx_value = mx_match.group(1) if mx_match else f"{domain.replace('.', '-')}.mail.protection.outlook.com"
        spf_value = spf_match.group(1) if spf_match else "v=spf1 include:spf.protection.outlook.com -all"

        logger.info(f"[{domain}] MX: {mx_value}")
        logger.info(f"[{domain}] SPF: {spf_value}")

        for retry in range(3):
            try:
                add_mx(zone_id, mx_value, 0)
                add_spf(zone_id, spf_value)
                add_cname(zone_id, "autodiscover", "autodiscover.outlook.com")

                result["success"] = True
                result["mx_value"] = mx_value
                result["spf_value"] = spf_value
                logger.info(f"[{domain}] DNS records added to Cloudflare")
                return result
            except Exception as e:
                logger.warning(f"[{domain}] Cloudflare API error (attempt {retry+1}): {e}")
                time.sleep(5)

    except Exception as e:
        logger.error(f"[{domain}] DNS phase error: {e}")

    return result


# ============================================================
# PHASE 5A: DKIM CNAMEs
# ============================================================

def phase_dkim_cnames(domain, zone_id, admin_email, onmicrosoft_domain):
    """Add DKIM CNAME records to Cloudflare. Constructs from known Microsoft pattern."""
    from app.services.cloudflare_sync import add_cname

    result = {"success": False, "selector1": None, "selector2": None}

    try:
        if not onmicrosoft_domain:
            onmicrosoft_domain = admin_email.split("@")[1] if "@" in admin_email else None
        if not onmicrosoft_domain:
            result["error"] = "No onmicrosoft domain available"
            return result

        domain_sanitized = domain.replace(".", "-")
        sel1 = f"selector1-{domain_sanitized}._domainkey.{onmicrosoft_domain}"
        sel2 = f"selector2-{domain_sanitized}._domainkey.{onmicrosoft_domain}"

        logger.info(f"[{domain}] DKIM selector1: {sel1}")
        logger.info(f"[{domain}] DKIM selector2: {sel2}")

        for retry in range(3):
            try:
                add_cname(zone_id, f"selector1._domainkey", sel1)
                add_cname(zone_id, f"selector2._domainkey", sel2)

                result["success"] = True
                result["selector1"] = sel1
                result["selector2"] = sel2
                logger.info(f"[{domain}] DKIM CNAMEs added (proxied=False)")
                return result
            except Exception as e:
                logger.warning(f"[{domain}] DKIM CNAME Cloudflare error (attempt {retry+1}): {e}")
                time.sleep(5)

    except Exception as e:
        logger.error(f"[{domain}] DKIM CNAME phase error: {e}")

    return result


# ============================================================
# PHASE 5B: DKIM ENABLE
# ============================================================

def phase_dkim_enable(driver, domain, admin_email, admin_password, totp_secret):
    """Enable DKIM signing in Exchange Admin Center. Retries up to 5 times."""
    MAX_DKIM_ATTEMPTS = 5

    for attempt in range(1, MAX_DKIM_ATTEMPTS + 1):
        logger.info(f"[{domain}] DKIM ENABLE attempt {attempt}/{MAX_DKIM_ATTEMPTS}")
        try:
            driver.get("https://admin.exchange.microsoft.com/#/dkim")
            time.sleep(8)
            dismiss_popups(driver)
            save_screenshot(driver, domain, f"dkim_page_a{attempt}")

            # Check if login needed for Exchange
            page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
            if "sign in" in page_text or "enter password" in page_text:
                logger.info(f"[{domain}] Exchange requires re-login")
                try:
                    pwd = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
                    pwd.send_keys(admin_password)
                    pwd.send_keys(Keys.ENTER)
                    time.sleep(4)

                    code = get_fresh_totp(totp_secret)
                    try:
                        totp_input = WebDriverWait(driver, 8).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='otc'], input[type='tel']"))
                        )
                        totp_input.send_keys(code)
                        totp_input.send_keys(Keys.ENTER)
                        time.sleep(4)
                    except TimeoutException:
                        pass

                    try:
                        find_and_click(driver, [(By.ID, "idSIButton9")], "Stay signed in", domain, timeout=5)
                        time.sleep(3)
                    except Exception:
                        pass

                    driver.get("https://admin.exchange.microsoft.com/#/dkim")
                    time.sleep(8)
                    dismiss_popups(driver)
                except Exception:
                    pass

            # Check if domain is in DKIM list
            page_text = driver.find_element(By.TAG_NAME, "body").text
            if domain.lower() not in page_text.lower():
                logger.warning(f"[{domain}] Not in DKIM list yet (Microsoft provisioning delay)")
                save_screenshot(driver, domain, f"dkim_not_in_list_a{attempt}")
                if attempt < MAX_DKIM_ATTEMPTS:
                    wait = 120 * attempt
                    logger.info(f"[{domain}] Waiting {wait}s for Microsoft to provision DKIM...")
                    time.sleep(wait)
                    continue
                else:
                    logger.warning(f"[{domain}] DKIM not provisioned — deferring to background job")
                    return False

            # Click on domain row
            clicked = find_and_click(driver, [
                (By.XPATH, f"//div[contains(text(), '{domain}')]/ancestor::div[@role='row']"),
                (By.XPATH, f"//span[contains(text(), '{domain}')]/ancestor::div[@role='row']"),
                (By.XPATH, f"//*[contains(text(), '{domain}')]"),
            ], f"DKIM row for {domain}", domain)

            if not clicked:
                continue

            time.sleep(3)
            dismiss_popups(driver)

            # Toggle DKIM signing on
            find_and_click(driver, [
                (By.XPATH, "//button[contains(@aria-label, 'Sign') or contains(text(), 'Sign')]"),
                (By.XPATH, "//div[contains(@class, 'ms-Toggle')]//button"),
                (By.XPATH, "//button[@role='switch']"),
            ], "DKIM toggle", domain)
            time.sleep(3)

            # Confirm dialog
            find_and_click(driver, [
                (By.XPATH, "//button[contains(text(), 'OK')]"),
                (By.XPATH, "//button[contains(text(), 'Confirm')]"),
                (By.XPATH, "//button[contains(text(), 'Enable')]"),
            ], "DKIM confirm dialog", domain, timeout=5)
            time.sleep(5)

            save_screenshot(driver, domain, f"dkim_after_enable_a{attempt}")

            # Check for success
            try:
                page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
                if "enabled" in page_text or "signing" in page_text:
                    logger.info(f"[{domain}] DKIM ENABLED")
                    return True
            except Exception:
                pass

            logger.info(f"[{domain}] DKIM enable attempt {attempt} — status unclear")

        except Exception as e:
            logger.error(f"[{domain}] DKIM enable attempt {attempt} error: {e}")
            save_screenshot(driver, domain, f"dkim_enable_error_a{attempt}")

        if attempt < MAX_DKIM_ATTEMPTS:
            time.sleep(30)

    logger.warning(f"[{domain}] DKIM enable incomplete — background job will retry")
    return False
