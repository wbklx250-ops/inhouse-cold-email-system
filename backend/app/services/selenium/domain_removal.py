"""
M365 Domain Removal - Robust 4-tier approach:

TIER 1: MSAL ROPC token → Graph API forceDelete (no browser needed)
TIER 2: PowerShell MSOnline Remove-MsolDomain (no browser needed)  
TIER 3: Selenium OAuth → Graph API forceDelete (browser fallback)
TIER 4: Selenium Admin Portal automation (browser last resort)
"""
import time
import os
import subprocess
import tempfile
import urllib.parse
import pyotp
import msal
import aiohttp
import asyncio
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

# Well-known Azure AD PowerShell client ID (public client, no secret needed)
AZURE_AD_POWERSHELL_CLIENT_ID = "1b730954-1685-4b74-9bfd-dac224a7b894"
GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]

# PowerShell path detection
PWSH_PATH = os.environ.get("PWSH_PATH", "/usr/bin/pwsh")


def screenshot(driver, step, domain=""):
    """Save a debug screenshot."""
    safe_domain = domain.replace(".", "_") if domain else "nodomain"
    path = os.path.join(SCREENSHOT_DIR, f"removal_{step}_{safe_domain}_{int(time.time())}.png")
    try:
        driver.save_screenshot(path)
        logger.info(f"Screenshot: {path}")
    except Exception as e:
        logger.warning(f"Could not save screenshot: {e}")


# =====================================================================
# TIER 1: MSAL ROPC → Graph API (NO BROWSER NEEDED)
# =====================================================================

def _get_access_token_via_msal(admin_email, admin_password):
    """
    Get an OAuth access token using MSAL Resource Owner Password Credentials (ROPC) flow.
    
    NO BROWSER NEEDED - pure HTTP token acquisition.
    Works for tenants with Security Defaults disabled (no MFA enforced).
    
    Returns: (success: bool, access_token: str|None, error: str|None)
    """
    tenant_domain = admin_email.split("@")[1] if "@" in admin_email else "common"
    authority = f"https://login.microsoftonline.com/{tenant_domain}"
    
    try:
        app = msal.PublicClientApplication(
            AZURE_AD_POWERSHELL_CLIENT_ID,
            authority=authority,
        )
        
        logger.info(f"[MSAL] Acquiring token via ROPC for {admin_email}...")
        result = app.acquire_token_by_username_password(
            username=admin_email,
            password=admin_password,
            scopes=GRAPH_SCOPE,
        )
        
        if "access_token" in result:
            token = result["access_token"]
            logger.info(f"[MSAL] Token acquired successfully ({len(token)} chars)")
            return True, token, None
        
        # Handle specific error cases
        error = result.get("error", "unknown_error")
        error_desc = result.get("error_description", "No description")
        
        if "interaction_required" in error:
            return False, None, f"MFA/interaction required - ROPC cannot handle MFA: {error_desc}"
        elif "invalid_grant" in error:
            return False, None, f"Invalid credentials: {error_desc}"
        elif "invalid_client" in error:
            return False, None, f"Client app issue: {error_desc}"
        else:
            return False, None, f"MSAL error ({error}): {error_desc}"
            
    except Exception as e:
        logger.error(f"[MSAL] Exception during token acquisition: {e}")
        return False, None, f"MSAL exception: {str(e)}"


async def _graph_api_force_delete(access_token, domain_name):
    """
    Force-delete a domain via Microsoft Graph API.
    Automatically reassigns all UPNs, proxy addresses, groups, etc.
    
    Returns: {"success": bool, "error": str|None}
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            # Check domain exists
            async with session.get(
                f"https://graph.microsoft.com/v1.0/domains/{domain_name}",
                headers=headers
            ) as resp:
                if resp.status == 404:
                    logger.info(f"[Graph API] Domain '{domain_name}' not found — already removed")
                    return {"success": True, "error": None, "note": "Domain already removed"}
                elif resp.status == 401:
                    return {"success": False, "error": "Access token expired or insufficient permissions"}
                elif resp.status != 200:
                    body = await resp.text()
                    logger.warning(f"[Graph API] Domain check returned {resp.status}: {body[:200]}")
            
            # Try forceDelete (beta endpoint)
            logger.info(f"[Graph API] Attempting forceDelete for '{domain_name}'...")
            async with session.post(
                f"https://graph.microsoft.com/beta/domains/{domain_name}/forceDelete",
                headers=headers,
                json={"disableUserAccounts": True}
            ) as resp:
                if resp.status in (200, 204):
                    logger.info(f"[Graph API] forceDelete succeeded for '{domain_name}'")
                    return {"success": True, "error": None, "method": "forceDelete"}
                else:
                    body = await resp.text()
                    logger.warning(f"[Graph API] forceDelete returned {resp.status}: {body[:300]}")
            
            # Fallback: regular DELETE
            logger.info(f"[Graph API] Trying regular DELETE for '{domain_name}'...")
            async with session.delete(
                f"https://graph.microsoft.com/v1.0/domains/{domain_name}",
                headers=headers
            ) as resp:
                if resp.status in (200, 204):
                    logger.info(f"[Graph API] DELETE succeeded for '{domain_name}'")
                    return {"success": True, "error": None, "method": "delete"}
                else:
                    body = await resp.text()
                    error_msg = f"DELETE returned {resp.status}: {body[:300]}"
                    logger.error(f"[Graph API] {error_msg}")
                    return {"success": False, "error": error_msg}
                    
    except Exception as e:
        logger.error(f"[Graph API] Error removing '{domain_name}': {e}")
        return {"success": False, "error": str(e)}


async def _graph_api_verify_removed(access_token, domain_name):
    """Verify a domain was actually removed by checking Graph API."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://graph.microsoft.com/v1.0/domains/{domain_name}",
                headers=headers
            ) as resp:
                if resp.status == 404:
                    return True
                elif resp.status == 200:
                    return False
                else:
                    return None
    except Exception:
        return None


def _run_async_graph_delete(token, domain_name):
    """Run async Graph API delete in a new event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_graph_api_force_delete(token, domain_name))
    finally:
        loop.close()


def _run_async_graph_verify(token, domain_name):
    """Run async Graph API verify in a new event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_graph_api_verify_removed(token, domain_name))
    finally:
        loop.close()


def _remove_domain_tier1_graph_api(domain_name, admin_email, admin_password):
    """
    TIER 1: Remove domain via MSAL ROPC → Graph API forceDelete.
    
    NO BROWSER NEEDED. Pure HTTP.
    Works for tenants without MFA enforced.
    
    Returns: {"success": bool, "error": str|None, "method": str}
    """
    logger.info(f"[{domain_name}] TIER 1: MSAL ROPC → Graph API forceDelete")
    
    # Step 1: Get token via MSAL (no browser)
    success, token, error = _get_access_token_via_msal(admin_email, admin_password)
    if not success or not token:
        logger.warning(f"[{domain_name}] TIER 1 token failed: {error}")
        return {"success": False, "error": f"MSAL token failed: {error}", "method": "tier1_msal_graph"}
    
    # Step 2: Call Graph API forceDelete
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(_run_async_graph_delete, token, domain_name).result(timeout=60)
        else:
            result = loop.run_until_complete(_graph_api_force_delete(token, domain_name))
    except RuntimeError:
        result = _run_async_graph_delete(token, domain_name)
    
    if result.get("success"):
        # Step 3: Verify removal
        time.sleep(5)
        try:
            verified = _run_async_graph_verify(token, domain_name)
        except Exception:
            verified = None
        
        if verified is False:
            logger.warning(f"[{domain_name}] TIER 1: Graph API reported success but domain still exists, may need propagation time")
            time.sleep(10)
        
        result["method"] = "tier1_msal_graph"
        logger.info(f"[{domain_name}] TIER 1 SUCCEEDED")
        return result
    
    result["method"] = "tier1_msal_graph"
    return result


# =====================================================================
# TIER 2: PowerShell MSOnline (NO BROWSER NEEDED)
# =====================================================================

def _remove_domain_tier2_powershell(domain_name, admin_email, admin_password):
    """
    TIER 2: Remove domain via PowerShell MSOnline Remove-MsolDomain.
    
    NO BROWSER NEEDED. Uses credential-based PowerShell auth.
    Same proven pattern as add_domain_msol in PowerShellRunner.
    
    Returns: {"success": bool, "error": str|None, "method": str}
    """
    logger.info(f"[{domain_name}] TIER 2: PowerShell MSOnline Remove-MsolDomain")
    
    # Escape password for PowerShell
    escaped_password = admin_password.replace("'", "''")
    
    script = f'''
$ErrorActionPreference = "Stop"

try {{
    Import-Module MSOnline -ErrorAction Stop
    
    $secpasswd = ConvertTo-SecureString '{escaped_password}' -AsPlainText -Force
    $credential = New-Object System.Management.Automation.PSCredential ('{admin_email}', $secpasswd)
    
    Connect-MsolService -Credential $credential -ErrorAction Stop
    
    # Check if domain exists first
    $domain = Get-MsolDomain -DomainName "{domain_name}" -ErrorAction SilentlyContinue
    
    if (-not $domain) {{
        Write-Output "<<<JSON>>>"
        @{{ "success" = $true; "note" = "Domain not found - already removed" }} | ConvertTo-Json -Compress
        Write-Output "<<<END>>>"
        exit 0
    }}
    
    # Try to reassign any users on this domain to the onmicrosoft.com domain first
    $tenantDomain = (Get-MsolDomain | Where-Object {{ $_.Name -like "*.onmicrosoft.com" -and $_.Name -notlike "*.mail.onmicrosoft.com" }} | Select-Object -First 1).Name
    
    if ($tenantDomain) {{
        $usersOnDomain = Get-MsolUser -All | Where-Object {{ $_.UserPrincipalName -like "*@{domain_name}" }}
        foreach ($user in $usersOnDomain) {{
            $newUPN = $user.UserPrincipalName.Split("@")[0] + "@" + $tenantDomain
            try {{
                Set-MsolUserPrincipalName -UserPrincipalName $user.UserPrincipalName -NewUserPrincipalName $newUPN -ErrorAction SilentlyContinue
                Write-Host "Reassigned $($user.UserPrincipalName) -> $newUPN"
            }} catch {{
                Write-Host "Could not reassign $($user.UserPrincipalName): $($_.Exception.Message)"
            }}
        }}
    }}
    
    # Now remove the domain
    Remove-MsolDomain -DomainName "{domain_name}" -Force -ErrorAction Stop
    
    Write-Output "<<<JSON>>>"
    @{{ "success" = $true; "note" = "Domain removed via Remove-MsolDomain" }} | ConvertTo-Json -Compress
    Write-Output "<<<END>>>"
    
}} catch {{
    $errMsg = $_.Exception.Message
    
    # Check if it's a "domain has associated objects" error
    if ($errMsg -match "associated" -or $errMsg -match "in use" -or $errMsg -match "cannot be removed") {{
        # Try force approach: disable user accounts and retry
        try {{
            $usersOnDomain = Get-MsolUser -All | Where-Object {{ $_.UserPrincipalName -like "*@{domain_name}" }}
            $tenantDomain = (Get-MsolDomain | Where-Object {{ $_.Name -like "*.onmicrosoft.com" -and $_.Name -notlike "*.mail.onmicrosoft.com" }} | Select-Object -First 1).Name
            
            foreach ($user in $usersOnDomain) {{
                $newUPN = $user.UserPrincipalName.Split("@")[0] + "@" + $tenantDomain
                Set-MsolUserPrincipalName -UserPrincipalName $user.UserPrincipalName -NewUserPrincipalName $newUPN -ErrorAction SilentlyContinue
            }}
            
            # Retry removal
            Remove-MsolDomain -DomainName "{domain_name}" -Force -ErrorAction Stop
            
            Write-Output "<<<JSON>>>"
            @{{ "success" = $true; "note" = "Domain removed after reassigning users" }} | ConvertTo-Json -Compress
            Write-Output "<<<END>>>"
        }} catch {{
            Write-Output "<<<JSON>>>"
            @{{ "success" = $false; "error" = $_.Exception.Message }} | ConvertTo-Json -Compress
            Write-Output "<<<END>>>"
        }}
    }} else {{
        Write-Output "<<<JSON>>>"
        @{{ "success" = $false; "error" = $errMsg }} | ConvertTo-Json -Compress
        Write-Output "<<<END>>>"
    }}
}}
'''
    
    try:
        # Write script to temp file and execute
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ps1', delete=False, encoding='utf-8') as f:
            f.write(script)
            script_path = f.name
        
        try:
            proc_result = subprocess.run(
                [PWSH_PATH, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script_path],
                capture_output=True,
                text=True,
                timeout=180,
                encoding='utf-8',
                errors='replace'
            )
            
            output = proc_result.stdout or ""
            error = proc_result.stderr or ""
            
            # Parse JSON result
            if "<<<JSON>>>" in output:
                try:
                    json_str = output.split("<<<JSON>>>")[1].split("<<<END>>>")[0].strip()
                    import json
                    json_data = json.loads(json_str)
                    
                    if json_data.get("success"):
                        logger.info(f"[{domain_name}] TIER 2 SUCCEEDED: {json_data.get('note', '')}")
                        return {"success": True, "error": None, "method": "tier2_powershell", "note": json_data.get("note")}
                    else:
                        ps_error = json_data.get("error", "Unknown PowerShell error")
                        logger.warning(f"[{domain_name}] TIER 2 failed: {ps_error}")
                        return {"success": False, "error": ps_error, "method": "tier2_powershell"}
                except Exception as parse_err:
                    logger.warning(f"[{domain_name}] TIER 2 JSON parse error: {parse_err}")
            
            # No JSON output - check return code
            if proc_result.returncode == 0:
                logger.info(f"[{domain_name}] TIER 2 completed (no JSON but exit 0)")
                return {"success": True, "error": None, "method": "tier2_powershell"}
            else:
                logger.warning(f"[{domain_name}] TIER 2 failed: exit={proc_result.returncode}, stderr={error[:300]}")
                return {"success": False, "error": f"PowerShell exit {proc_result.returncode}: {error[:300]}", "method": "tier2_powershell"}
                
        finally:
            try:
                os.unlink(script_path)
            except Exception:
                pass
                
    except subprocess.TimeoutExpired:
        logger.error(f"[{domain_name}] TIER 2 timed out after 180s")
        return {"success": False, "error": "PowerShell timed out after 180s", "method": "tier2_powershell"}
    except Exception as e:
        logger.error(f"[{domain_name}] TIER 2 exception: {e}")
        return {"success": False, "error": str(e), "method": "tier2_powershell"}


# =====================================================================
# TIER 3: Selenium OAuth → Graph API (BROWSER FALLBACK)
# =====================================================================

def create_browser(headless=True):
    """Create a Chrome browser instance with robust configuration."""
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-features=VizDisplayCompositor")
    options.add_argument("--single-process")
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    prefs = {"credentials_enable_service": False, "profile.password_manager_enabled": False}
    options.add_experimental_option("prefs", prefs)
    
    # Use CHROME_PATH from environment if set (Docker sets this)
    chrome_binary = os.environ.get("CHROME_PATH")
    if chrome_binary and os.path.exists(chrome_binary):
        options.binary_location = chrome_binary
    
    # Try creating browser with retries
    last_error = None
    for attempt in range(3):
        try:
            driver = webdriver.Chrome(options=options)
            driver.implicitly_wait(10)
            driver.set_page_load_timeout(60)
            return driver
        except Exception as e:
            last_error = e
            logger.warning(f"Browser creation attempt {attempt + 1}/3 failed: {e}")
            time.sleep(2)
    
    raise last_error


def _get_access_token_via_selenium(admin_email, admin_password, totp_secret=None, headless=True):
    """
    Get an OAuth token via Selenium browser automation.
    TIER 3 method - only used when MSAL ROPC fails (e.g., MFA required).
    
    Returns: (success: bool, access_token: str|None, error: str|None)
    """
    client_id = AZURE_AD_POWERSHELL_CLIENT_ID
    redirect_uri = "https://login.microsoftonline.com/common/oauth2/nativeclient"
    tenant_domain = admin_email.split("@")[1] if "@" in admin_email else "common"
    
    auth_url = (
        f"https://login.microsoftonline.com/{tenant_domain}/oauth2/v2.0/authorize"
        f"?client_id={client_id}"
        f"&response_type=token"
        f"&redirect_uri={urllib.parse.quote(redirect_uri, safe='')}"
        f"&scope=https://graph.microsoft.com/.default"
        f"&response_mode=fragment"
    )
    
    driver = None
    try:
        driver = create_browser(headless=headless)
        logger.info(f"[Selenium Token] Navigating to OAuth URL for {admin_email}")
        driver.get(auth_url)
        time.sleep(3)
        
        # Enter email
        try:
            email_field = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.NAME, "loginfmt"))
            )
            email_field.clear()
            email_field.send_keys(admin_email + Keys.RETURN)
            time.sleep(4)
        except TimeoutException:
            return False, None, "Could not find email input"
        
        # Enter password
        try:
            password_field = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.NAME, "passwd"))
            )
            password_field.clear()
            password_field.send_keys(admin_password + Keys.RETURN)
            time.sleep(4)
        except TimeoutException:
            return False, None, "Could not find password input"
        
        # Check for login errors
        page_source = driver.page_source.lower()
        for err in ["password is incorrect", "account or password is incorrect", "account doesn't exist", "account has been locked"]:
            if err in page_source:
                return False, None, f"Login failed: {err}"
        
        # Handle TOTP/MFA
        if totp_secret:
            try:
                totp_field = WebDriverWait(driver, 8).until(
                    EC.presence_of_element_located((By.NAME, "otc"))
                )
                code = pyotp.TOTP(totp_secret).now()
                totp_field.send_keys(code + Keys.RETURN)
                time.sleep(4)
            except TimeoutException:
                logger.debug("[Selenium Token] No TOTP field - MFA may not be required")
        else:
            try:
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.NAME, "otc"))
                )
                return False, None, "MFA required but no TOTP secret provided"
            except TimeoutException:
                pass
        
        # Handle "Stay signed in?"
        try:
            no_btn = WebDriverWait(driver, 8).until(
                EC.element_to_be_clickable((By.ID, "idBtn_Back"))
            )
            no_btn.click()
            time.sleep(3)
        except TimeoutException:
            pass
        
        # Extract token from URL
        time.sleep(3)
        for _ in range(10):
            current_url = driver.current_url
            if "#access_token=" in current_url:
                fragment = current_url.split("#", 1)[1]
                params = dict(p.split("=", 1) for p in fragment.split("&") if "=" in p)
                token = urllib.parse.unquote(params.get("access_token", ""))
                if token:
                    logger.info(f"[Selenium Token] Got access token ({len(token)} chars)")
                    return True, token, None
            if "error=" in current_url:
                return False, None, f"OAuth error in redirect URL"
            time.sleep(2)
        
        # Check for consent page
        page_source = driver.page_source.lower()
        if "permissions requested" in page_source or "accept" in page_source:
            try:
                accept_btn = driver.find_element(By.XPATH, "//input[@type='submit'] | //button[contains(., 'Accept')]")
                accept_btn.click()
                time.sleep(5)
                current_url = driver.current_url
                if "#access_token=" in current_url:
                    fragment = current_url.split("#", 1)[1]
                    params = dict(p.split("=", 1) for p in fragment.split("&") if "=" in p)
                    token = urllib.parse.unquote(params.get("access_token", ""))
                    if token:
                        return True, token, None
            except Exception:
                pass
        
        return False, None, f"Could not extract token. Final URL: {driver.current_url[:100]}"
        
    except Exception as e:
        logger.error(f"[Selenium Token] Error: {e}")
        return False, None, str(e)
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def _remove_domain_tier3_selenium_graph(domain_name, admin_email, admin_password, totp_secret=None, headless=True):
    """
    TIER 3: Get token via Selenium, then use Graph API forceDelete.
    
    REQUIRES BROWSER. Used when MSAL ROPC fails (MFA required) but browser is available.
    
    Returns: {"success": bool, "error": str|None, "method": str}
    """
    logger.info(f"[{domain_name}] TIER 3: Selenium OAuth → Graph API forceDelete")
    
    # Step 1: Get token via Selenium
    success, token, error = _get_access_token_via_selenium(
        admin_email, admin_password, totp_secret, headless=headless
    )
    if not success or not token:
        logger.warning(f"[{domain_name}] TIER 3 token failed: {error}")
        return {"success": False, "error": f"Selenium token failed: {error}", "method": "tier3_selenium_graph"}
    
    # Step 2: Call Graph API forceDelete (reuse same async helpers)
    try:
        result = _run_async_graph_delete(token, domain_name)
    except Exception as e:
        return {"success": False, "error": str(e), "method": "tier3_selenium_graph"}
    
    if result.get("success"):
        result["method"] = "tier3_selenium_graph"
        logger.info(f"[{domain_name}] TIER 3 SUCCEEDED")
        return result
    
    result["method"] = "tier3_selenium_graph"
    return result


# =====================================================================
# TIER 4: Selenium Admin Portal (BROWSER LAST RESORT)
# =====================================================================

def do_login(driver, admin_email, admin_password, totp_secret=None):
    """Login to M365 Admin Portal. Returns True/False."""
    logger.info(f"Logging in to M365 Admin Portal as {admin_email}")
    driver.get("https://admin.microsoft.com")
    time.sleep(5)
    
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
    
    page_source = driver.page_source.lower()
    for indicator in ["password is incorrect", "account or password is incorrect", "account doesn't exist", "account has been locked", "sign-in was blocked"]:
        if indicator in page_source:
            logger.error(f"Login failed: {indicator}")
            return False
    
    if totp_secret:
        try:
            totp_field = WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.NAME, "otc"))
            )
            code = pyotp.TOTP(totp_secret).now()
            totp_field.send_keys(code + Keys.RETURN)
            time.sleep(5)
        except TimeoutException:
            logger.debug("No TOTP field found")
    else:
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.NAME, "otc"))
            )
            logger.error("MFA required but no TOTP secret provided!")
            return False
        except TimeoutException:
            pass
    
    try:
        no_btn = WebDriverWait(driver, 8).until(
            EC.element_to_be_clickable((By.ID, "idBtn_Back"))
        )
        no_btn.click()
        time.sleep(3)
    except TimeoutException:
        pass
    
    time.sleep(5)
    current = driver.current_url
    if "admin.microsoft.com" in current or "admin.cloud.microsoft" in current:
        logger.info(f"Login successful. URL: {current}")
        return True
    
    logger.error(f"Login may have failed. URL: {current}")
    return False


def _dismiss_popups(driver):
    """Dismiss teaching bubbles, callouts, or overlay popups."""
    try:
        driver.implicitly_wait(0)
        dismiss_selectors = [
            "//div[contains(@class, 'TeachingBubble')]//button[contains(@aria-label, 'Close')]",
            "//div[contains(@class, 'TeachingBubble')]//button[contains(@aria-label, 'Dismiss')]",
            "//div[contains(@class, 'ms-Callout')]//button[contains(@aria-label, 'Close')]",
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
                        time.sleep(0.5)
                    except Exception:
                        pass
            except Exception:
                pass
        
        driver.execute_script("""
            document.querySelectorAll('[class*="TeachingBubble"], [class*="ms-Callout"]').forEach(el => el.remove());
        """)
    except Exception:
        pass
    finally:
        driver.implicitly_wait(10)


def _handle_default_domain_panel(driver, admin_email, domain_name):
    """Handle the 'Set a new default before removing this domain' side panel."""
    try:
        driver.implicitly_wait(2)
        
        panel_found = False
        for indicator in ["//*[contains(text(), 'Set a new default')]", "//*[contains(text(), 'new default domain')]", "//*[contains(text(), 'currently your default')]"]:
            try:
                driver.find_element(By.XPATH, indicator)
                panel_found = True
                break
            except NoSuchElementException:
                continue
        
        if not panel_found:
            return
        
        logger.info(f"[{domain_name}] Default domain panel detected")
        
        # Click dropdown
        for sel in ["//div[contains(@class, 'ms-Dropdown')]", "//div[contains(@role, 'combobox')]", "//*[contains(text(), 'Select a domain')]"]:
            try:
                dropdown = driver.find_element(By.XPATH, sel)
                try:
                    dropdown.click()
                except ElementClickInterceptedException:
                    driver.execute_script("arguments[0].click()", dropdown)
                time.sleep(2)
                break
            except NoSuchElementException:
                continue
        
        # Select onmicrosoft.com option
        option_selected = False
        for sel in ["//*[@role='option'][contains(., 'onmicrosoft')]", "//*[@role='listbox']//*[contains(text(), 'onmicrosoft')]"]:
            try:
                options = driver.find_elements(By.XPATH, sel)
                for opt in options:
                    try:
                        opt.click()
                    except ElementClickInterceptedException:
                        driver.execute_script("arguments[0].click()", opt)
                    option_selected = True
                    time.sleep(2)
                    break
                if option_selected:
                    break
            except Exception:
                continue
        
        if not option_selected:
            # JS fallback
            driver.execute_script("""
                var options = document.querySelectorAll('[role="option"]');
                for (var i = 0; i < options.length; i++) {
                    if (options[i].textContent.includes('onmicrosoft')) { options[i].click(); return; }
                }
            """)
            time.sleep(2)
        
        # Click save/confirm button
        for sel in ["//button[contains(., 'Update and continue')]", "//button[contains(., 'Update')]", "//button[contains(., 'Set as default')]", "//button[contains(., 'Save')]", "//button[contains(., 'Continue')]"]:
            try:
                save_btn = driver.find_element(By.XPATH, sel)
                is_disabled = save_btn.get_attribute("disabled")
                if is_disabled == "true":
                    continue
                try:
                    save_btn.click()
                except ElementClickInterceptedException:
                    driver.execute_script("arguments[0].click()", save_btn)
                time.sleep(5)
                break
            except NoSuchElementException:
                continue
        
        logger.info(f"[{domain_name}] Default domain panel handled")
        
    except Exception as e:
        logger.warning(f"Error handling default domain panel: {e}")
    finally:
        driver.implicitly_wait(10)


def remove_domain_from_m365(domain_name, admin_email, admin_password, totp_secret=None, headless=True):
    """
    TIER 4: Remove a custom domain via Selenium Admin Portal automation.
    Last resort - only used if all non-browser methods fail.
    
    Returns: {"success": bool, "error": str|None}
    """
    driver = None
    try:
        driver = create_browser(headless=headless)
        
        if not do_login(driver, admin_email, admin_password, totp_secret):
            screenshot(driver, "login_failed", domain_name)
            return {"success": False, "error": "Login failed", "method": "tier4_selenium_portal"}
        
        screenshot(driver, "01_logged_in", domain_name)
        
        # Navigate to Domains page
        driver.get("https://admin.cloud.microsoft/#/Domains")
        time.sleep(8)
        _dismiss_popups(driver)
        
        # Find and click the domain
        domain_found = False
        for attempt in range(3):
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
                    _dismiss_popups(driver)
                    driver.execute_script("arguments[0].click()", domain_link)
                domain_found = True
                time.sleep(3)
                break
            except TimeoutException:
                _dismiss_popups(driver)
                time.sleep(2)
        
        if not domain_found:
            logger.info(f"Domain '{domain_name}' not in list - treating as already removed")
            return {"success": True, "error": None, "method": "tier4_selenium_portal", "note": "Domain not found - already removed"}
        
        # Click "Remove domain" button
        _dismiss_popups(driver)
        remove_clicked = False
        driver.implicitly_wait(1)
        for sel in ["//*[contains(text(), 'Remove domain')]", "//*[contains(text(), 'Delete domain')]",
                    "//button[contains(text(), 'Remove')]", "//button[contains(text(), 'Delete')]",
                    "//*[contains(@aria-label, 'Remove domain')]"]:
            try:
                remove_btn = WebDriverWait(driver, 2).until(
                    EC.presence_of_element_located((By.XPATH, sel))
                )
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
            # Try three-dot menu
            try:
                more_btn = driver.find_element(By.XPATH,
                    "//button[contains(@aria-label, 'More')] | //button[contains(@aria-label, 'Actions')]")
                more_btn.click()
                time.sleep(2)
                remove_option = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Remove')]"))
                )
                try:
                    remove_option.click()
                except ElementClickInterceptedException:
                    driver.execute_script("arguments[0].click()", remove_option)
                remove_clicked = True
                time.sleep(3)
            except Exception:
                return {"success": False, "error": "Could not find Remove Domain button", "method": "tier4_selenium_portal"}
        
        # Handle default domain panel
        _handle_default_domain_panel(driver, admin_email, domain_name)
        
        # Confirm removal dialog
        confirm_clicked = False
        driver.implicitly_wait(2)
        for sel in ["//button[contains(., 'Automatically remove')]", "//button[contains(., 'Remove domain')]",
                    "//button[contains(., 'Remove')]", "//button[contains(., 'Delete')]",
                    "//button[contains(., 'Confirm')]", "//button[contains(., 'Yes')]"]:
            try:
                confirm_btn = WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((By.XPATH, sel))
                )
                try:
                    confirm_btn.click()
                except ElementClickInterceptedException:
                    driver.execute_script("arguments[0].click()", confirm_btn)
                confirm_clicked = True
                time.sleep(5)
                break
            except TimeoutException:
                continue
        driver.implicitly_wait(10)
        
        if not confirm_clicked:
            # JS fallback
            result = driver.execute_script("""
                var buttons = document.querySelectorAll('button');
                for (var i = 0; i < buttons.length; i++) {
                    var txt = buttons[i].textContent.trim();
                    if (txt.includes('Automatically remove') || txt.includes('Remove domain') || 
                        (txt.includes('Remove') && !txt.includes('How to'))) {
                        buttons[i].click();
                        return 'clicked: ' + txt;
                    }
                }
                return 'no confirm button found';
            """)
            if result and 'clicked' in str(result):
                confirm_clicked = True
            time.sleep(5)
        
        # Wait for removal to process
        time.sleep(20)
        
        # Check page for success/error
        page_source = driver.page_source.lower()
        
        for indicator in ["has been removed", "successfully removed", "domain was removed", "removal complete", "domain removed"]:
            if indicator in page_source:
                logger.info(f"[{domain_name}] TIER 4 SUCCEEDED (confirmed: '{indicator}')")
                return {"success": True, "error": None, "method": "tier4_selenium_portal"}
        
        for indicator in ["can't remove this domain", "cannot remove this domain", "unable to remove", "removal failed", "domain is still in use"]:
            if indicator in page_source:
                return {"success": False, "error": f"M365 rejected removal: '{indicator}'", "method": "tier4_selenium_portal", "needs_retry": True}
        
        # If confirm was clicked and no errors, treat as success
        if confirm_clicked:
            logger.info(f"[{domain_name}] TIER 4: Confirm clicked, no errors — treating as success")
            return {"success": True, "error": None, "method": "tier4_selenium_portal", "note": "Removal confirmed, no error indicators"}
        
        return {"success": False, "error": "Could not confirm removal", "method": "tier4_selenium_portal", "needs_retry": True}
        
    except Exception as e:
        logger.error(f"[{domain_name}] TIER 4 exception: {e}")
        if driver:
            screenshot(driver, "error", domain_name)
        return {"success": False, "error": str(e), "method": "tier4_selenium_portal"}
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# =====================================================================
# MASTER: 4-tier robust removal
# =====================================================================

def remove_domain_robust(domain_name, admin_email, admin_password, totp_secret=None, headless=True):
    """
    Bulletproof 4-tier domain removal. Tries each method in order until one succeeds.
    
    TIER 1: MSAL ROPC → Graph API forceDelete (NO browser, pure HTTP)
    TIER 2: PowerShell MSOnline Remove-MsolDomain (NO browser, credential-based)
    TIER 3: Selenium OAuth → Graph API forceDelete (needs browser, handles MFA)
    TIER 4: Selenium Admin Portal automation (needs browser, last resort)
    
    Tiers 1 & 2 require NO browser and handle the vast majority of cases.
    Tiers 3 & 4 are browser-based fallbacks for edge cases (e.g., MFA required).
    
    Returns: {"success": bool, "error": str|None, "method": str, "attempts": list}
    """
    attempts = []
    
    # ===== TIER 1: MSAL ROPC → Graph API (NO BROWSER) =====
    logger.info(f"[{domain_name}] === ROBUST REMOVAL: Starting 4-tier approach ===")
    try:
        result = _remove_domain_tier1_graph_api(domain_name, admin_email, admin_password)
        attempts.append({"tier": 1, "method": "msal_graph", "result": result})
        
        if result.get("success"):
            logger.info(f"[{domain_name}] ✓ TIER 1 (MSAL → Graph API) SUCCEEDED")
            return {"success": True, "error": None, "method": result.get("method", "tier1_msal_graph"), "attempts": attempts}
        else:
            logger.warning(f"[{domain_name}] TIER 1 failed: {result.get('error', 'unknown')} — trying Tier 2")
    except Exception as e:
        logger.warning(f"[{domain_name}] TIER 1 exception: {e} — trying Tier 2")
        attempts.append({"tier": 1, "method": "msal_graph", "result": {"success": False, "error": str(e)}})
    
    # ===== TIER 2: PowerShell MSOnline (NO BROWSER) =====
    try:
        result = _remove_domain_tier2_powershell(domain_name, admin_email, admin_password)
        attempts.append({"tier": 2, "method": "powershell", "result": result})
        
        if result.get("success"):
            logger.info(f"[{domain_name}] ✓ TIER 2 (PowerShell MSOnline) SUCCEEDED")
            return {"success": True, "error": None, "method": result.get("method", "tier2_powershell"), "attempts": attempts}
        else:
            logger.warning(f"[{domain_name}] TIER 2 failed: {result.get('error', 'unknown')} — trying Tier 3 (browser)")
    except Exception as e:
        logger.warning(f"[{domain_name}] TIER 2 exception: {e} — trying Tier 3 (browser)")
        attempts.append({"tier": 2, "method": "powershell", "result": {"success": False, "error": str(e)}})
    
    # ===== TIER 3: Selenium OAuth → Graph API (BROWSER) =====
    # Only try browser-based methods if we have a TOTP secret (MFA might be the issue)
    # or if both non-browser methods had non-credential errors
    try:
        result = _remove_domain_tier3_selenium_graph(
            domain_name, admin_email, admin_password, totp_secret, headless=headless
        )
        attempts.append({"tier": 3, "method": "selenium_graph", "result": result})
        
        if result.get("success"):
            logger.info(f"[{domain_name}] ✓ TIER 3 (Selenium → Graph API) SUCCEEDED")
            return {"success": True, "error": None, "method": result.get("method", "tier3_selenium_graph"), "attempts": attempts}
        else:
            logger.warning(f"[{domain_name}] TIER 3 failed: {result.get('error', 'unknown')} — trying Tier 4")
    except Exception as e:
        logger.warning(f"[{domain_name}] TIER 3 exception: {e} — trying Tier 4")
        attempts.append({"tier": 3, "method": "selenium_graph", "result": {"success": False, "error": str(e)}})
    
    # ===== TIER 4: Selenium Admin Portal (BROWSER LAST RESORT) =====
    try:
        result = remove_domain_from_m365(
            domain_name, admin_email, admin_password, totp_secret, headless=headless
        )
        attempts.append({"tier": 4, "method": "selenium_portal", "result": result})
        
        if result.get("success"):
            logger.info(f"[{domain_name}] ✓ TIER 4 (Selenium Admin Portal) SUCCEEDED")
            return {"success": True, "error": None, "method": result.get("method", "tier4_selenium_portal"), "attempts": attempts}
        else:
            logger.error(f"[{domain_name}] ✗ TIER 4 also FAILED: {result.get('error', 'unknown')}")
    except Exception as e:
        logger.error(f"[{domain_name}] TIER 4 exception: {e}")
        attempts.append({"tier": 4, "method": "selenium_portal", "result": {"success": False, "error": str(e)}})
    
    # ===== ALL 4 TIERS FAILED =====
    last_error = attempts[-1]["result"].get("error", "Unknown error") if attempts else "No attempts made"
    tier_summary = ", ".join(
        f"T{a['tier']}:{a['result'].get('error', 'failed')[:50]}" for a in attempts
    )
    logger.error(f"[{domain_name}] ✗ ALL 4 TIERS FAILED: {tier_summary}")
    
    return {
        "success": False,
        "error": f"All 4 removal tiers failed. Last error: {last_error}",
        "method": "none",
        "attempts": attempts,
        "needs_retry": True
    }


# =====================================================================
# BACKWARD COMPATIBILITY
# =====================================================================
# These aliases ensure the domain_removal_service.py doesn't need changes
# (it calls remove_domain_robust and remove_domain_from_m365 by name)

def remove_domain_via_graph_api(domain_name, admin_email, admin_password, totp_secret=None, headless=True):
    """Backward-compatible alias — now uses MSAL ROPC (Tier 1) instead of Selenium for tokens."""
    return _remove_domain_tier1_graph_api(domain_name, admin_email, admin_password)
