"""
SMTP Auth Fixer (PowerShell-first with MFA fallback)
====================================================

Implements the standalone "SMTP AUTH Fixer" flow in-app:
1) Try ExchangeOnline PowerShell (fast) to enable SMTP AUTH + verify
2) If MFA blocks, caller can disable Security Defaults and retry
3) Handles WAM errors by preferring pwsh and disabling WAM registry on Windows
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
from typing import Optional, Dict

logger = logging.getLogger(__name__)

EXO_REQUIRED_VERSION = os.getenv("EXO_REQUIRED_VERSION", "").strip()

MFA_ERROR_PATTERNS = [
    "AADSTS50076", "AADSTS50079", "AADSTS53003", "AADSTS50158",
    "AADSTS65001", "multi-factor", "MFA", "interaction_required",
    "security defaults", "Conditional Access",
]

WAM_ERROR_PATTERNS = [
    "WAM Error", "WAM_error", "3399614467", "3400073293",
    "Web Account Manager", "WAM_provider",
]

TRANSIENT_ERROR_PATTERNS = [
    "copying content to a stream",
    "connection was closed",
    "transport error",
    "network",
    "timed out",
    "timeout",
]


def _contains_any(msg: str, patterns: list[str]) -> bool:
    if not msg:
        return False
    upper = msg.upper()
    return any(p.upper() in upper for p in patterns)


def is_mfa_error(msg: str) -> bool:
    return _contains_any(msg, MFA_ERROR_PATTERNS)


def is_wam_error(msg: str) -> bool:
    if not msg:
        return False
    return any(p in msg for p in WAM_ERROR_PATTERNS)


def is_transient_error(msg: str) -> bool:
    if not msg:
        return False
    lower = msg.lower()
    return any(p in lower for p in TRANSIENT_ERROR_PATTERNS)


def find_powershell_exe(prefer_pwsh: bool = True) -> Optional[str]:
    """
    Find the best PowerShell executable.
    Prefers pwsh (PowerShell 7+) over powershell (5.1) when available.
    """
    candidates: list[str] = []
    if prefer_pwsh:
        candidates.extend(["pwsh", "pwsh.exe"])
    candidates.extend(["powershell", "powershell.exe"])

    for exe in candidates:
        try:
            r = subprocess.run(
                [exe, "-Command", "Write-Output 'ok'"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if "ok" in (r.stdout or ""):
                return exe
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        except Exception:
            continue

    return None


def disable_wam_registry() -> bool:
    """
    Disable WAM for ExchangeOnlineManagement via Windows Registry.
    Only runs on Windows.
    """
    if os.name != "nt":
        return False

    try:
        import winreg
    except Exception:
        return False

    ok = False
    try:
        key_path = r"Software\Microsoft\Exchange"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE)
        except FileNotFoundError:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)

        winreg.SetValueEx(key, "AlwaysUseMSOLClient", 0, winreg.REG_DWORD, 1)
        winreg.CloseKey(key)
        ok = True
    except Exception as e:
        logger.warning("Could not set AlwaysUseMSOLClient WAM disable: %s", e)

    try:
        key_path = r"Software\Microsoft\Exchange\ClientAuthentication"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE)
        except FileNotFoundError:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)

        winreg.SetValueEx(key, "DisableWAM", 0, winreg.REG_DWORD, 1)
        winreg.CloseKey(key)
        ok = True
    except Exception as e:
        logger.warning("Could not set DisableWAM registry key: %s", e)

    return ok


def _build_smtp_auth_ps_script(
    admin_email: str,
    admin_password: str,
    verify_only: bool = False,
) -> str:
    escaped_pass = admin_password.replace("'", "''")
    import_line = "Import-Module ExchangeOnlineManagement -ErrorAction Stop"
    if EXO_REQUIRED_VERSION:
        import_line = f"Import-Module ExchangeOnlineManagement -RequiredVersion {EXO_REQUIRED_VERSION} -ErrorAction Stop"

    if verify_only:
        return f"""
$ErrorActionPreference = "Stop"
$maxRetries = 3
$connected = $false
{import_line}
$sp = ConvertTo-SecureString '{escaped_pass}' -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential('{admin_email}', $sp)

for ($attempt = 1; $attempt -le $maxRetries; $attempt++) {{
    try {{
        Connect-ExchangeOnline -Credential $cred -ShowBanner:$false -ErrorAction Stop
        $connected = $true
        break
    }} catch {{
        if ($attempt -lt $maxRetries) {{ Start-Sleep -Seconds 3 }} else {{ throw }}
    }}
}}

try {{
    $d = (Get-TransportConfig).SmtpClientAuthenticationDisabled
    Disconnect-ExchangeOnline -Confirm:$false -ErrorAction SilentlyContinue
    @{{ success=$true; smtp_auth_enabled=(-not $d); action="verify_only"; verified=$true; error=$null }} | ConvertTo-Json -Compress
}} catch {{
    try {{ Disconnect-ExchangeOnline -Confirm:$false -ErrorAction SilentlyContinue }} catch {{}}
    @{{ success=$false; smtp_auth_enabled=$false; action="error"; verified=$false; error=$_.Exception.Message }} | ConvertTo-Json -Compress
}}
"""

    return f"""
$ErrorActionPreference = "Stop"
$maxRetries = 3
$connected = $false
{import_line}
$sp = ConvertTo-SecureString '{escaped_pass}' -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential('{admin_email}', $sp)

for ($attempt = 1; $attempt -le $maxRetries; $attempt++) {{
    try {{
        Connect-ExchangeOnline -Credential $cred -ShowBanner:$false -ErrorAction Stop
        $connected = $true
        break
    }} catch {{
        if ($attempt -lt $maxRetries) {{ Start-Sleep -Seconds 3 }} else {{ throw }}
    }}
}}

try {{
    $before = (Get-TransportConfig).SmtpClientAuthenticationDisabled
    $action = "none"

    if ($before -eq $true) {{
        Set-TransportConfig -SmtpClientAuthenticationDisabled $false -ErrorAction Stop
        Start-Sleep -Seconds 2
        $action = "enabled"
    }} elseif ($before -eq $false) {{
        $action = "already_enabled"
    }}

    $after = (Get-TransportConfig).SmtpClientAuthenticationDisabled
    $verified = ($after -eq $false)

    Disconnect-ExchangeOnline -Confirm:$false -ErrorAction SilentlyContinue
    @{{ success=$verified; smtp_auth_enabled=$verified; action=$action; verified=$verified; error=$null }} | ConvertTo-Json -Compress
}} catch {{
    try {{ Disconnect-ExchangeOnline -Confirm:$false -ErrorAction SilentlyContinue }} catch {{}}
    @{{ success=$false; smtp_auth_enabled=$false; action="error"; verified=$false; error=$_.Exception.Message }} | ConvertTo-Json -Compress
}}
"""


async def _run_powershell_script(ps_exe: str, script: str, timeout: int = 180) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["MSAL_FORCE_BROKER_DISABLED"] = "true"
    env["MSAL_DISABLE_WAM"] = "true"
    env["EXO_DISABLE_WAM"] = "true"

    def _run_sync():
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", delete=False, encoding="utf-8") as f:
            f.write(script)
            script_path = f.name

        try:
            return subprocess.run(
                [ps_exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                encoding="utf-8",
                errors="replace",
            )
        finally:
            try:
                os.unlink(script_path)
            except Exception:
                pass

    return await asyncio.to_thread(_run_sync)


async def run_smtp_auth_powershell(
    ps_exe: str,
    admin_email: str,
    admin_password: str,
    verify_only: bool = False,
) -> Dict:
    script = _build_smtp_auth_ps_script(
        admin_email=admin_email,
        admin_password=admin_password,
        verify_only=verify_only,
    )

    try:
        proc = await _run_powershell_script(ps_exe, script, timeout=180)
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        combined = f"{stdout}\n{stderr}".strip()

        json_line = None
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith("{"):
                json_line = line
                break

        if json_line:
            try:
                parsed = json.loads(json_line)
            except Exception:
                parsed = {
                    "success": False,
                    "smtp_auth_enabled": False,
                    "action": "error",
                    "verified": False,
                    "error": combined[:400],
                }
        else:
            parsed = {
                "success": False,
                "smtp_auth_enabled": False,
                "action": "error",
                "verified": False,
                "error": combined[:400],
            }

        err_msg = parsed.get("error") or ""
        parsed["mfa_blocked"] = is_mfa_error(err_msg)
        parsed["wam_error"] = is_wam_error(err_msg)
        parsed["ps_exe"] = ps_exe
        return parsed

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "smtp_auth_enabled": False,
            "action": "timeout",
            "verified": False,
            "error": "PowerShell timed out (180s)",
            "mfa_blocked": False,
            "wam_error": False,
            "ps_exe": ps_exe,
        }
    except Exception as e:
        msg = str(e)
        return {
            "success": False,
            "smtp_auth_enabled": False,
            "action": "error",
            "verified": False,
            "error": msg,
            "mfa_blocked": is_mfa_error(msg),
            "wam_error": is_wam_error(msg),
            "ps_exe": ps_exe,
        }


async def run_smtp_auth_with_retry(
    ps_exe: str,
    admin_email: str,
    admin_password: str,
    verify_only: bool = False,
    max_attempts: int = 3,
) -> Dict:
    result: Dict = {}
    for attempt in range(1, max_attempts + 1):
        result = await run_smtp_auth_powershell(
            ps_exe=ps_exe,
            admin_email=admin_email,
            admin_password=admin_password,
            verify_only=verify_only,
        )
        if result.get("success") or not is_transient_error(result.get("error") or ""):
            break
        if attempt < max_attempts:
            await asyncio.sleep(5)
    return result


async def enable_smtp_auth_with_powershell(
    admin_email: str,
    admin_password: str,
    ps_exe_state: Dict[str, Optional[str]],
    ps_exe_lock: asyncio.Lock,
    verify_only: bool = False,
) -> Dict:
    ps_exe = ps_exe_state.get("exe")
    if not ps_exe:
        return {
            "success": False,
            "smtp_auth_enabled": False,
            "action": "error",
            "verified": False,
            "error": "PowerShell not available (pwsh/powershell not found)",
            "mfa_blocked": False,
            "wam_error": False,
            "ps_exe": None,
        }

    result = await run_smtp_auth_with_retry(
        ps_exe=ps_exe,
        admin_email=admin_email,
        admin_password=admin_password,
        verify_only=verify_only,
    )

    if result.get("wam_error") and os.name == "nt":
        logger.warning("WAM error detected. Attempting registry fix and pwsh switch.")
        disable_wam_registry()

        alt_ps = await asyncio.to_thread(find_powershell_exe, True)
        if alt_ps and alt_ps != ps_exe:
            async with ps_exe_lock:
                ps_exe_state["exe"] = alt_ps
            ps_exe = alt_ps

        result = await run_smtp_auth_with_retry(
            ps_exe=ps_exe,
            admin_email=admin_email,
            admin_password=admin_password,
            verify_only=verify_only,
        )

    return result
