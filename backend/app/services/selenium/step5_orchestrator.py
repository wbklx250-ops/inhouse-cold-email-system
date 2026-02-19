"""
Step 5 Orchestrator — Master function that ties all phases together.

run_domain_setup_bulletproof() — Full domain setup with guaranteed cleanup
try_dkim_enable_standalone() — For background DKIM retry job
"""

import time
import logging
import traceback

from app.services.selenium.step5_helpers import (
    create_chrome, destroy_chrome, save_screenshot,
    DNS_WAIT, DKIM_WAIT,
)
from app.services.selenium.step5_phases import (
    phase_login, phase_add_domain, phase_verify_domain,
    phase_dns_records, phase_dkim_cnames, phase_dkim_enable,
)

logger = logging.getLogger(__name__)


def run_domain_setup_bulletproof(
    domain_name,
    zone_id,
    admin_email,
    admin_password,
    totp_secret,
    onmicrosoft_domain,
    needs_add,
    needs_verify,
    needs_dns,
    needs_dkim_cnames,
    needs_dkim_enable,
    headless=True,
):
    """
    BULLETPROOF domain setup. Fresh Chrome, guaranteed cleanup, checkpoint-aware.

    Returns dict with keys:
      domain_added, txt_value, domain_verified, dns_configured,
      dkim_cnames_added, dkim_selector1, dkim_selector2,
      dkim_enabled, success, error
    """
    logger.info(f"[{domain_name}] ========== BULLETPROOF DOMAIN SETUP ==========")
    logger.info(f"[{domain_name}] Needs: add={needs_add}, verify={needs_verify}, "
                f"dns={needs_dns}, dkim_cnames={needs_dkim_cnames}, dkim_enable={needs_dkim_enable}")

    driver = None
    profile_dir = None
    result = {
        "domain_added": False,
        "txt_value": None,
        "domain_verified": False,
        "dns_configured": False,
        "dkim_cnames_added": False,
        "dkim_selector1": None,
        "dkim_selector2": None,
        "dkim_enabled": False,
        "success": False,
        "error": None,
        "mx_value": None,
        "spf_value": None,
    }

    try:
        # ===== CREATE BROWSER =====
        driver, profile_dir = create_chrome(headless=headless)

        # ===== PHASE 1: LOGIN =====
        if any([needs_add, needs_verify, needs_dns, needs_dkim_enable]):
            if not phase_login(driver, admin_email, admin_password, totp_secret, domain_name):
                result["error"] = "Login failed"
                return result

        # ===== PHASE 2: ADD DOMAIN (if needed) =====
        if needs_add:
            add_result = phase_add_domain(driver, domain_name)

            if not add_result["success"]:
                result["error"] = "Add domain failed"
                return result

            result["domain_added"] = True

            if add_result.get("already_verified"):
                result["domain_verified"] = True
                needs_verify = False
                logger.info(f"[{domain_name}] Domain already verified in M365")
            elif add_result.get("txt_value"):
                result["txt_value"] = add_result["txt_value"]

                # Add TXT to Cloudflare
                from app.services.cloudflare_sync import add_txt
                for retry in range(3):
                    try:
                        add_txt(zone_id, add_result["txt_value"])
                        logger.info(f"[{domain_name}] TXT record added to Cloudflare")
                        break
                    except Exception as e:
                        logger.warning(f"[{domain_name}] Cloudflare TXT error (retry {retry+1}): {e}")
                        time.sleep(5)
        else:
            result["domain_added"] = True  # Already done in previous run

        # ===== PHASE 3: VERIFY (if needed) =====
        if needs_verify:
            logger.info(f"[{domain_name}] Waiting {DNS_WAIT}s for DNS propagation...")
            time.sleep(DNS_WAIT)

            if phase_verify_domain(driver, domain_name):
                result["domain_verified"] = True
            else:
                result["error"] = "Verification failed after retries"
                return result
        else:
            result["domain_verified"] = True  # Already done

        # ===== HANDLE "HOW DO YOU WANT TO CONNECT" PAGE =====
        # After verification, M365 may show a "connect domain" page
        try:
            from selenium.webdriver.common.by import By
            from app.services.selenium.step5_helpers import (
                detect_page_state, find_and_click, dismiss_popups,
            )

            time.sleep(3)
            state = detect_page_state(driver, domain_name)

            if state == "connect_domain":
                logger.info(f"[{domain_name}] On 'Connect domain' page — selecting 'Add your own DNS records'")

                # Click "More options"
                find_and_click(driver, [
                    (By.XPATH, "//*[contains(text(), 'More options')]"),
                ], "More options", domain_name, timeout=5)
                time.sleep(2)

                # Select "Add your own DNS records"
                for xpath in [
                    "//input[@type='radio'][following-sibling::*[contains(text(), 'Add your own')]]",
                    "//input[@type='radio'][..//*[contains(text(), 'Add your own')]]",
                    "//*[contains(text(), 'Add your own DNS records')]",
                    "//span[contains(text(), 'Add your own DNS records')]",
                ]:
                    try:
                        el = driver.find_element(By.XPATH, xpath)
                        driver.execute_script("arguments[0].click();", el)
                        logger.info(f"[{domain_name}] Selected 'Add your own DNS records'")
                        break
                    except Exception:
                        continue
                time.sleep(1)

                # Click Continue
                find_and_click(driver, [
                    (By.XPATH, "//button[contains(text(), 'Continue')]"),
                    (By.XPATH, "//button[contains(text(), 'Next')]"),
                ], "Continue button", domain_name)
                time.sleep(5)

        except Exception as e:
            logger.warning(f"[{domain_name}] Connect page handling: {e}")

        # ===== PHASE 4: DNS RECORDS (if needed) =====
        if needs_dns:
            dns_result = phase_dns_records(driver, domain_name, zone_id)
            if dns_result["success"]:
                result["dns_configured"] = True
                result["mx_value"] = dns_result.get("mx_value")
                result["spf_value"] = dns_result.get("spf_value")
            else:
                logger.warning(f"[{domain_name}] DNS records failed but continuing...")
                result["dns_configured"] = False
        else:
            result["dns_configured"] = True

        # ===== PHASE 5A: DKIM CNAMES (if needed) =====
        if needs_dkim_cnames:
            dkim_result = phase_dkim_cnames(
                domain_name, zone_id, admin_email, onmicrosoft_domain
            )
            if dkim_result["success"]:
                result["dkim_cnames_added"] = True
                result["dkim_selector1"] = dkim_result["selector1"]
                result["dkim_selector2"] = dkim_result["selector2"]
            else:
                result["error"] = "DKIM CNAME creation failed"
                return result
        else:
            result["dkim_cnames_added"] = True

        # ===== PHASE 5B: DKIM ENABLE (if needed) =====
        if needs_dkim_enable:
            logger.info(f"[{domain_name}] Waiting {DKIM_WAIT}s for DKIM CNAME propagation...")
            time.sleep(DKIM_WAIT)

            dkim_on = phase_dkim_enable(driver, domain_name, admin_email, admin_password, totp_secret)
            result["dkim_enabled"] = dkim_on

            if not dkim_on:
                logger.info(f"[{domain_name}] DKIM enable deferred to background job")
        else:
            result["dkim_enabled"] = True

        # ===== DETERMINE OVERALL SUCCESS =====
        # Success = verified + DNS + DKIM CNAMEs (DKIM enable is optional — background job handles it)
        result["success"] = (
            result["domain_verified"]
            and result["dns_configured"]
            and result["dkim_cnames_added"]
        )

        if result["dkim_enabled"]:
            logger.info(f"[{domain_name}] ========== FULL SUCCESS ==========")
        elif result["success"]:
            logger.info(f"[{domain_name}] ========== PARTIAL SUCCESS (DKIM deferred) ==========")
        else:
            result["error"] = result.get("error") or "Partial failure"

        return result

    except Exception as e:
        logger.error(f"[{domain_name}] FATAL: {e}")
        logger.error(traceback.format_exc())
        if driver:
            save_screenshot(driver, domain_name, "fatal_error")
        result["error"] = str(e)[:500]
        return result

    finally:
        # ===== GUARANTEED CLEANUP =====
        destroy_chrome(driver, profile_dir)
        logger.info(f"[{domain_name}] Browser destroyed and cleaned up")


def try_dkim_enable_standalone(domain_name, admin_email, admin_password, totp_secret):
    """Standalone DKIM enable attempt with its own browser. For background retry job."""
    driver = None
    profile_dir = None
    try:
        driver, profile_dir = create_chrome(headless=True)
        if phase_login(driver, admin_email, admin_password, totp_secret, domain_name):
            return phase_dkim_enable(driver, domain_name, admin_email, admin_password, totp_secret)
        return False
    except Exception as e:
        logger.error(f"[{domain_name}] Standalone DKIM enable error: {e}")
        return False
    finally:
        destroy_chrome(driver, profile_dir)
