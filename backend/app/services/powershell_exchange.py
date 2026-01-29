"""
PowerShell Exchange Service - Uses device code auth with Selenium MFA handling.
"""

import os

if os.environ.get("ENABLE_NEST_ASYNCIO") == "1":
    import nest_asyncio
    nest_asyncio.apply()

import asyncio
import subprocess
import re
import logging
import json
from typing import List, Dict, Any, Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

logger = logging.getLogger(__name__)


class PowerShellExchangeService:
    """
    Execute Exchange operations via PowerShell with device code auth.
    Selenium handles the device code login + MFA.
    """

    def __init__(self, driver: webdriver.Chrome, admin_email: str, admin_password: str, totp_secret: str = None):
        self.driver = driver
        self.admin_email = admin_email
        self.admin_password = admin_password
        self.totp_secret = totp_secret
        self.ps_process = None
        self.connected = False

    @staticmethod
    def _ps_escape(value: str) -> str:
        """Escape string for safe use in PowerShell double-quoted strings."""
        if value is None:
            return ""
        return value.replace("`", "``").replace('"', '`"')

    async def connect(self) -> bool:
        """
        Connect to Exchange Online using device code flow.
        Selenium handles the interactive login.
        """
        logger.info("Starting PowerShell Exchange connection with device code...")

        # Start PowerShell process
        self.ps_process = subprocess.Popen(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        # Import module and start device code auth
        connect_cmd = '''
Import-Module ExchangeOnlineManagement -ErrorAction Stop
Write-Output "MODULE_LOADED"
Connect-ExchangeOnline -Device -ErrorAction Stop
Write-Output "CONNECTED_SUCCESS"
'''

        # Send command
        self.ps_process.stdin.write(connect_cmd)
        self.ps_process.stdin.flush()

        # Read output looking for device code
        device_code = None
        timeout = 30
        start = time.time()

        while time.time() - start < timeout:
            line = self.ps_process.stdout.readline()
            if not line:
                await asyncio.sleep(0.1)
                continue

            line = line.strip()
            logger.debug("PS Output: %s", line)

            # Look for device code pattern
            # "To sign in, use a web browser to open the page https://microsoft.com/devicelogin and enter the code XXXXXXXX to authenticate."
            code_match = re.search(r"enter the code\s+([A-Z0-9]{8,})", line, re.IGNORECASE)
            if code_match:
                device_code = code_match.group(1)
                logger.info("Got device code: %s", device_code)
                break

            # Alternative pattern
            code_match2 = re.search(r"code[:\s]+([A-Z0-9]{8,})", line, re.IGNORECASE)
            if code_match2:
                device_code = code_match2.group(1)
                logger.info("Got device code (alt): %s", device_code)
                break

            if "MODULE_LOADED" in line:
                logger.info("Exchange module loaded")

        if not device_code:
            logger.error("Failed to get device code from PowerShell")
            return False

        # Use Selenium to complete device code login
        success = await self._complete_device_login(device_code)

        if success:
            # Wait for PowerShell to confirm connection
            timeout = 60
            start = time.time()

            while time.time() - start < timeout:
                line = self.ps_process.stdout.readline()
                if not line:
                    await asyncio.sleep(0.5)
                    continue

                line = line.strip()
                logger.debug("PS Output: %s", line)

                if "CONNECTED_SUCCESS" in line or "completed" in line.lower():
                    self.connected = True
                    logger.info("✓ PowerShell connected to Exchange Online!")
                    return True

            # Check if we're actually connected
            test_result = await self._run_command(
                "Get-OrganizationConfig | Select-Object Name | ConvertTo-Json"
            )
            if test_result and "Name" in str(test_result):
                self.connected = True
                logger.info("✓ PowerShell connected to Exchange Online (verified)!")
                return True

        logger.error("Failed to complete device code authentication")
        return False

    async def _complete_device_login(self, device_code: str) -> bool:
        """Complete device code login using Selenium, handling all Microsoft screens."""

        logger.info("Completing device login with code: %s", device_code)

        try:
            # Navigate to device login page
            self.driver.get("https://microsoft.com/devicelogin")
            await asyncio.sleep(2)

            # Enter device code
            code_input = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.ID, "otc"))
            )
            code_input.clear()
            code_input.send_keys(device_code)

            # Click Next
            next_btn = self.driver.find_element(By.ID, "idSIButton9")
            next_btn.click()
            await asyncio.sleep(3)

            # SCREEN 1: "Pick an account"
            page_source = self.driver.page_source.lower()
            if "pick an account" in page_source or "choose an account" in page_source:
                logger.info("Account picker detected, clicking existing account...")
                try:
                    account_tile = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, "div.table"))
                    )
                    account_tile.click()
                    await asyncio.sleep(3)
                except Exception:
                    try:
                        first_account = self.driver.find_element(By.CSS_SELECTOR, "[data-test-id]")
                        first_account.click()
                        await asyncio.sleep(3)
                    except Exception:
                        pass

            # SCREEN 2: "Are you trying to sign in to Microsoft Exchange..."
            await asyncio.sleep(2)
            page_source = self.driver.page_source.lower()
            if "are you trying to sign in" in page_source or "microsoft exchange" in page_source:
                logger.info("Consent screen detected, clicking Continue...")
                try:
                    continue_btn = WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable((By.ID, "idSIButton9"))
                    )
                    continue_btn.click()
                    await asyncio.sleep(3)
                except Exception as e:
                    logger.warning("Continue button: %s", e)

            # SCREEN 3: Password entry (if session expired)
            page_source = self.driver.page_source.lower()
            if "enter password" in page_source or "passwd" in self.driver.page_source:
                logger.info("Password entry detected...")
                try:
                    pwd_input = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.NAME, "passwd"))
                    )
                    pwd_input.clear()
                    pwd_input.send_keys(self.admin_password)
                    submit_btn = self.driver.find_element(By.ID, "idSIButton9")
                    submit_btn.click()
                    await asyncio.sleep(3)
                except Exception:
                    pass

            # SCREEN 4: MFA/TOTP
            await self._handle_mfa()

            # SCREEN 5: "Stay signed in?"
            await asyncio.sleep(2)
            try:
                page_source = self.driver.page_source.lower()
                if "stay signed in" in page_source:
                    yes_btn = self.driver.find_element(By.ID, "idSIButton9")
                    yes_btn.click()
                    await asyncio.sleep(2)
            except Exception:
                pass

            # Check for success
            await asyncio.sleep(3)
            page_source = self.driver.page_source.lower()
            if (
                "you have signed in" in page_source
                or "you're signed in" in page_source
                or "close this window" in page_source
            ):
                logger.info("✓ Device code authentication successful!")
                return True

            return True

        except Exception as exc:
            logger.error("Device login failed: %s", exc)
            return False

    async def _handle_mfa(self):
        """Handle MFA challenge using TOTP."""

        await asyncio.sleep(2)
        page_source = self.driver.page_source.lower()

        # Check if TOTP input is present
        if (
            "authenticator" in page_source
            or "verification code" in page_source
            or "enter code" in page_source
        ):
            if self.totp_secret:
                import pyotp

                totp = pyotp.TOTP(self.totp_secret)
                code = totp.now()

                logger.info("Entering TOTP code for MFA")

                # Find and fill TOTP input
                try:
                    totp_input = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.NAME, "otc"))
                    )
                    totp_input.clear()
                    totp_input.send_keys(code)

                    verify_btn = self.driver.find_element(By.ID, "idSubmit_SAOTCC_Continue")
                    verify_btn.click()
                    await asyncio.sleep(3)
                except Exception:
                    # Try alternative input
                    try:
                        totp_input = self.driver.find_element(By.ID, "idTxtBx_SAOTCC_OTC")
                        totp_input.clear()
                        totp_input.send_keys(code)

                        verify_btn = self.driver.find_element(By.ID, "idSubmit_SAOTCC_Continue")
                        verify_btn.click()
                        await asyncio.sleep(3)
                    except Exception as exc:
                        logger.warning("Could not find TOTP input: %s", exc)

        # Handle "Stay signed in?" prompt
        try:
            stay_signed_in = self.driver.find_element(By.ID, "idBtn_Back")
            stay_signed_in.click()  # Click "No"
        except Exception:
            try:
                yes_btn = self.driver.find_element(By.ID, "idSIButton9")
                yes_btn.click()  # Click "Yes"
            except Exception:
                pass

    async def _run_command(self, command: str) -> Optional[str]:
        """Run a PowerShell command and return output."""

        if not self.ps_process:
            logger.error("PowerShell process not running")
            return None

        # Add output marker
        full_cmd = f"{command}\nWrite-Output \"CMD_COMPLETE\"\n"

        self.ps_process.stdin.write(full_cmd)
        self.ps_process.stdin.flush()

        # Collect output
        output_lines = []
        timeout = 120
        start = time.time()

        while time.time() - start < timeout:
            line = self.ps_process.stdout.readline()
            if not line:
                await asyncio.sleep(0.1)
                continue

            line = line.strip()

            if "CMD_COMPLETE" in line:
                break

            output_lines.append(line)

        return "\n".join(output_lines)

    async def create_shared_mailboxes(
        self,
        mailboxes: List[Dict[str, str]],
        delegate_to: str,
    ) -> Dict[str, Any]:
        """
        Create shared mailboxes with numbered names, fix display names, add delegation.

        Args:
            mailboxes: List of {"email": "...", "display_name": "...", "password": "..."}
            delegate_to: Licensed user email (me1@domain)
        """

        if not self.connected:
            raise Exception("Not connected to Exchange Online")

        results = {
            "created": [],
            "failed": [],
            "delegated": [],
            "upns_fixed": [],
        }

        base_display_name = mailboxes[0].get("display_name", "User") if mailboxes else "User"

        # STEP 1: Create mailboxes with NUMBERED display names
        logger.info("Creating %s shared mailboxes...", len(mailboxes))
        for i, mb in enumerate(mailboxes, 1):
            email = mb["email"]
            numbered_name = f"{base_display_name} {i}"

            create_cmd = f'''
try {{
    New-Mailbox -Shared -Name "{numbered_name}" -DisplayName "{numbered_name}" -PrimarySmtpAddress "{email}" -ErrorAction Stop | Out-Null
    Write-Output "CREATED:{email}"
}} catch {{
    if ($_.Exception.Message -like "*already exists*") {{
        Write-Output "EXISTS:{email}"
    }} else {{
        Write-Output "FAILED:{email}:$($_.Exception.Message)"
    }}
}}
'''
            output = await self._run_command(create_cmd)

            if output and (f"CREATED:{email}" in output or f"EXISTS:{email}" in output):
                results["created"].append(email)
                logger.info("  ✓ Created: %s", email)
            else:
                error_msg = output.split("FAILED:")[-1] if output and "FAILED:" in output else "Unknown error"
                results["failed"].append({"email": email, "error": error_msg})
                logger.error("  ✗ Failed: %s - %s", email, error_msg)

            await asyncio.sleep(0.3)

        # STEP 2: Fix display names (remove numbers, all same name)
        logger.info("Fixing display names to '%s'...", base_display_name)
        await asyncio.sleep(2)

        for mb in mailboxes:
            email = mb["email"]
            fix_cmd = f'''
try {{
    Set-Mailbox -Identity "{email}" -DisplayName "{base_display_name}" -ErrorAction Stop
    Write-Output "FIXED:{email}"
}} catch {{
    Write-Output "FIXFAILED:{email}:$($_.Exception.Message)"
}}
'''
            output = await self._run_command(fix_cmd)
            if output and f"FIXED:{email}" in output:
                logger.info("  ✓ Display name fixed: %s", email)

            await asyncio.sleep(0.2)

        # STEP 3: Add delegation (FullAccess + SendAs)
        logger.info("Adding delegation to %s...", delegate_to)
        await asyncio.sleep(2)

        for mb in mailboxes:
            email = mb["email"]
            delegate_cmd = f'''
try {{
    Add-MailboxPermission -Identity "{email}" -User "{delegate_to}" -AccessRights FullAccess -AutoMapping $true -ErrorAction SilentlyContinue | Out-Null
    Add-RecipientPermission -Identity "{email}" -Trustee "{delegate_to}" -AccessRights SendAs -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
    Write-Output "DELEGATED:{email}"
}} catch {{
    Write-Output "DELEGATEFAILED:{email}:$($_.Exception.Message)"
}}
'''
            output = await self._run_command(delegate_cmd)

            if output and f"DELEGATED:{email}" in output:
                results["delegated"].append(email)
                logger.info("  ✓ Delegated: %s -> %s", email, delegate_to)

            await asyncio.sleep(0.2)

        # STEP 4: Fix UPNs to match email addresses (critical for Graph API)
        logger.info("Fixing UPNs to match email addresses...")
        await asyncio.sleep(3)

        for mb in mailboxes:
            email = mb["email"]
            upn_cmd = f'''
try {{
    Set-Mailbox -Identity "{email}" -MicrosoftOnlineServicesID "{email}" -ErrorAction Stop
    Write-Output "UPNFIXED:{email}"
}} catch {{
    Write-Output "UPNFAILED:{email}:$($_.Exception.Message)"
}}
'''
            output = await self._run_command(upn_cmd)

            if output and f"UPNFIXED:{email}" in output:
                results["upns_fixed"].append(email)
                logger.info("  ✓ UPN fixed: %s", email)
            else:
                logger.warning("  ⚠ UPN fix issue: %s", email)

            await asyncio.sleep(0.2)

        logger.info(
            "PowerShell complete: %s created, %s delegated, %s UPNs fixed",
            len(results["created"]),
            len(results["delegated"]),
            len(results["upns_fixed"]),
        )
        return results

    async def set_mailbox_passwords(
        self,
        mailboxes: List[Dict[str, str]],
        admin_email: str,
        admin_password: str,
    ) -> Dict[str, Any]:
        """
        Set passwords, enable accounts, and fix UPNs for mailboxes using Microsoft Graph.

        Args:
            mailboxes: List of {"email": "...", "password": "..."}
            admin_email: Admin UPN for Graph connection
            admin_password: Admin password for Graph connection

        Returns:
            {"results": [...], "updated": [...], "failed": [...]}
        """

        if not self.connected:
            raise Exception("Not connected to Exchange Online")

        escaped_admin_email = self._ps_escape(admin_email)
        escaped_admin_password = self._ps_escape(admin_password)

        connect_graph_cmd = f'''
try {{
    Import-Module Microsoft.Graph.Users -ErrorAction Stop
    $securePassword = ConvertTo-SecureString "{escaped_admin_password}" -AsPlainText -Force
    $credential = New-Object System.Management.Automation.PSCredential("{escaped_admin_email}", $securePassword)
    Connect-MgGraph -Credential $credential -NoWelcome -ErrorAction Stop
    Write-Output "MG_CONNECTED"
}} catch {{
    Write-Output "MG_CONNECT_FAILED:$($_.Exception.Message)"
}}
'''

        connect_output = await self._run_command(connect_graph_cmd)
        if not connect_output or "MG_CONNECTED" not in connect_output:
            raise Exception(f"Microsoft Graph connection failed: {connect_output}")

        results = []
        updated = []
        failed = []

        for mb in mailboxes:
            email = mb["email"]
            password = mb.get("password", "")
            escaped_email = self._ps_escape(email)
            escaped_password = self._ps_escape(password)

            cmd = f'''
$mailboxEmail = "{escaped_email}"
$passwordValue = "{escaped_password}"
$errors = @()
$upnFixed = $false
$passwordSet = $false
$accountEnabled = $false

try {{
    $mailbox = Get-Mailbox -Identity $mailboxEmail -ErrorAction Stop
    $userPrincipalName = $mailbox.UserPrincipalName
    $user = Get-MgUser -UserId $userPrincipalName -ErrorAction Stop

    if ($user.UserPrincipalName -ne $mailboxEmail) {{
        try {{
            Update-MgUser -UserId $user.Id -UserPrincipalName $mailboxEmail -ErrorAction Stop
            $upnFixed = $true
        }} catch {{
            $errors += "Failed to update UPN: $($_.Exception.Message)"
        }}
    }} else {{
        $upnFixed = $true
    }}

    try {{
        $passwordProfile = @{{
            Password = $passwordValue
            ForceChangePasswordNextSignIn = $false
        }}
        Update-MgUser -UserId $user.Id -PasswordProfile $passwordProfile -ErrorAction Stop
        $passwordSet = $true
    }} catch {{
        $errors += "Failed to set password: $($_.Exception.Message)"
    }}

    try {{
        Update-MgUser -UserId $user.Id -AccountEnabled:$true -ErrorAction Stop
        $accountEnabled = $true
    }} catch {{
        $errors += "Failed to enable account: $($_.Exception.Message)"
    }}
}} catch {{
    $errors += "Mailbox lookup failed: $($_.Exception.Message)"
}}

$result = @{{
    email = $mailboxEmail
    upn_fixed = $upnFixed
    password_set = $passwordSet
    account_enabled = $accountEnabled
    errors = $errors
}}

if ($errors.Count -eq 0) {{
    $result.success = $true
}} else {{
    $result.success = $false
}}

$result | ConvertTo-Json -Compress
'''

            output = await self._run_command(cmd)
            parsed = None
            if output:
                for line in output.splitlines():
                    line = line.strip()
                    if line.startswith("{") and line.endswith("}"):
                        try:
                            parsed = json.loads(line)
                        except json.JSONDecodeError:
                            continue

            if parsed:
                results.append(parsed)
                if parsed.get("success"):
                    updated.append(parsed["email"])
                else:
                    failed.append({"email": parsed.get("email", email), "error": "; ".join(parsed.get("errors", []))})
            else:
                failed.append({"email": email, "error": output or "No output from PowerShell"})

            await asyncio.sleep(0.5)

        await self._run_command("Disconnect-MgGraph -ErrorAction SilentlyContinue")

        return {
            "results": results,
            "updated": updated,
            "failed": failed,
        }

    async def add_mailbox_delegation(
        self,
        mailboxes: List[Dict[str, str]],
        delegate_to: str,
    ) -> Dict[str, Any]:
        """
        Add mailbox delegation for a list of mailboxes.

        Args:
            mailboxes: List of {"email": "..."}
            delegate_to: User UPN to grant permissions to

        Returns:
            {"delegated": [...], "failed": [...]}
        """

        if not self.connected:
            raise Exception("Not connected to Exchange Online")

        results = {"delegated": [], "failed": []}
        escaped_delegate = self._ps_escape(delegate_to)

        for mb in mailboxes:
            email = mb["email"]
            escaped_email = self._ps_escape(email)

            cmd = f'''
$mailboxEmail = "{escaped_email}"
$delegateUser = "{escaped_delegate}"
$errors = @()

try {{
    Add-MailboxPermission -Identity $mailboxEmail -User $delegateUser -AccessRights FullAccess -InheritanceType All -AutoMapping $true -ErrorAction Stop | Out-Null
}} catch {{
    if ($_.Exception.Message -notlike "*already*") {{
        $errors += "Failed FullAccess: $($_.Exception.Message)"
    }}
}}

try {{
    Add-RecipientPermission -Identity $mailboxEmail -Trustee $delegateUser -AccessRights SendAs -Confirm:$false -ErrorAction Stop | Out-Null
}} catch {{
    if ($_.Exception.Message -notlike "*already*") {{
        $errors += "Failed SendAs: $($_.Exception.Message)"
    }}
}}

try {{
    Set-Mailbox -Identity $mailboxEmail -GrantSendOnBehalfTo @{{Add=$delegateUser}} -ErrorAction Stop | Out-Null
}} catch {{
    if ($_.Exception.Message -notlike "*already*") {{
        $errors += "Failed SendOnBehalf: $($_.Exception.Message)"
    }}
}}

if ($errors.Count -eq 0) {{
    Write-Output "DELEGATED:$mailboxEmail"
}} else {{
    Write-Output "DELEGATE_FAILED:$mailboxEmail:$($errors -join '; ')"
}}
'''

            output = await self._run_command(cmd)
            if output and f"DELEGATED:{email}" in output:
                results["delegated"].append(email)
            else:
                error_detail = "Delegation failed"
                if output and "DELEGATE_FAILED" in output:
                    error_detail = output.split("DELEGATE_FAILED:")[-1].strip()
                results["failed"].append({"email": email, "error": error_detail})

            await asyncio.sleep(0.5)

        return results

    async def fix_display_names(self, mailboxes: List[Dict[str, str]]) -> Dict[str, Any]:
        """Fix display names for mailboxes."""

        if not self.connected:
            raise Exception("Not connected to Exchange Online")

        results = {"updated": [], "failed": []}

        for mb in mailboxes:
            email = mb["email"]
            display_name = mb["display_name"]

            cmd = f'''
try {{
    Set-Mailbox -Identity "{email}" -DisplayName "{display_name}" -ErrorAction Stop
    Write-Output "UPDATED:{email}"
}} catch {{
    Write-Output "FAILED:{email}:$($_.Exception.Message)"
}}
'''
            output = await self._run_command(cmd)

            if output and f"UPDATED:{email}" in output:
                results["updated"].append(email)
                logger.info("  ✓ Updated display name: %s", email)
            else:
                error = (
                    output.split("FAILED:")[-1]
                    if output and "FAILED:" in output
                    else "Unknown error"
                )
                results["failed"].append({"email": email, "error": error})

        return results

    async def disconnect(self):
        """Disconnect from Exchange Online and cleanup."""

        if self.ps_process:
            try:
                self.ps_process.stdin.write("Disconnect-ExchangeOnline -Confirm:$false\nexit\n")
                self.ps_process.stdin.flush()
                self.ps_process.wait(timeout=10)
            except Exception:
                self.ps_process.kill()

            self.ps_process = None
            self.connected = False
            logger.info("Disconnected from Exchange Online")