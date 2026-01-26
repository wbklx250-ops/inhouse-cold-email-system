import asyncio
import json
from pathlib import Path
from typing import Dict, List, Optional


class PowerShellError(Exception):
    """Custom exception for PowerShell execution errors."""
    pass


class PowerShellService:
    """
    Execute PowerShell scripts for M365 operations.
    
    Operations requiring PowerShell (not available in Graph API):
    - Get-DkimSigningConfig (get DKIM CNAME values)
    - Set-DkimSigningConfig -Enabled $true (enable DKIM)
    - New-Mailbox -Shared (create shared mailboxes)
    - Add-MailboxPermission (delegation)
    """
    
    SCRIPTS_PATH = Path(__file__).parent.parent.parent / "scripts"
    
    async def execute_script(
        self, 
        script_name: str, 
        params: Dict
    ) -> Dict:
        """
        Execute a PowerShell script with parameters.
        
        Args:
            script_name: Name of the script file in the scripts directory
            params: Dictionary of parameters to pass to the script
            
        Returns: {
            "success": True/False,
            "output": "...",  # stdout (parsed JSON if valid)
            "error": "..."    # stderr if any
        }
        """
        script_path = self.SCRIPTS_PATH / script_name
        
        if not script_path.exists():
            return {
                "success": False,
                "output": "",
                "error": f"Script not found: {script_path}"
            }
        
        # Build PowerShell command with parameters
        # Use -NoProfile for faster startup, -NonInteractive to prevent prompts
        param_str = " ".join([f'-{k} "{v}"' for k, v in params.items()])
        cmd = f'pwsh -NoProfile -NonInteractive -File "{script_path}" {param_str}'
        
        try:
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            output = stdout.decode().strip() if stdout else ""
            error = stderr.decode().strip() if stderr else ""
            
            # Try to parse output as JSON
            parsed_output = output
            if output:
                try:
                    parsed_output = json.loads(output)
                except json.JSONDecodeError:
                    # Keep as string if not valid JSON
                    pass
            
            return {
                "success": process.returncode == 0,
                "output": parsed_output,
                "error": error
            }
            
        except Exception as e:
            return {
                "success": False,
                "output": "",
                "error": str(e)
            }
    
    async def get_dkim_config(
        self, 
        admin_email: str, 
        admin_password: str, 
        domain: str
    ) -> Dict:
        """
        Get DKIM CNAME values from M365.
        
        Args:
            admin_email: M365 admin email address
            admin_password: M365 admin password
            domain: Domain to get DKIM config for
            
        Returns: {
            "selector1_cname": "selector1-domain-com._domainkey.tenant.onmicrosoft.com",
            "selector2_cname": "selector2-domain-com._domainkey.tenant.onmicrosoft.com",
            "selector1_host": "selector1._domainkey",
            "selector2_host": "selector2._domainkey",
            "enabled": True/False
        }
        
        Raises:
            PowerShellError: If script execution fails
        """
        result = await self.execute_script("get_dkim_config.ps1", {
            "AdminEmail": admin_email,
            "AdminPassword": admin_password,
            "Domain": domain
        })
        
        if result["success"]:
            if isinstance(result["output"], dict):
                return result["output"]
            else:
                raise PowerShellError(f"Unexpected output format: {result['output']}")
        else:
            raise PowerShellError(f"Failed to get DKIM config: {result['error']}")
    
    async def enable_dkim(
        self, 
        admin_email: str, 
        admin_password: str, 
        domain: str
    ) -> bool:
        """
        Enable DKIM signing for domain.
        
        Args:
            admin_email: M365 admin email address
            admin_password: M365 admin password
            domain: Domain to enable DKIM for
            
        Returns:
            True if DKIM was enabled successfully
            
        Raises:
            PowerShellError: If script execution fails
        """
        result = await self.execute_script("enable_dkim.ps1", {
            "AdminEmail": admin_email,
            "AdminPassword": admin_password,
            "Domain": domain
        })
        
        if not result["success"]:
            raise PowerShellError(f"Failed to enable DKIM: {result['error']}")
        
        return True
    
    async def create_shared_mailboxes(
        self,
        admin_email: str,
        admin_password: str,
        mailboxes: List[Dict]  # [{"email": "...", "display_name": "..."}]
    ) -> List[Dict]:
        """
        Create multiple shared mailboxes.
        
        Args:
            admin_email: M365 admin email address
            admin_password: M365 admin password
            mailboxes: List of mailbox definitions with email and display_name
            
        Returns:
            List of created mailbox results with success/failure status
            
        Raises:
            PowerShellError: If script execution fails completely
        """
        # Convert mailboxes list to JSON string for PowerShell
        mailboxes_json = json.dumps(mailboxes)
        
        result = await self.execute_script("create_mailboxes.ps1", {
            "AdminEmail": admin_email,
            "AdminPassword": admin_password,
            "MailboxesJson": mailboxes_json.replace('"', '\\"')  # Escape quotes for command line
        })
        
        if result["success"]:
            if isinstance(result["output"], list):
                return result["output"]
            elif isinstance(result["output"], dict):
                return [result["output"]]
            else:
                return []
        else:
            raise PowerShellError(f"Failed to create mailboxes: {result['error']}")
    
    async def configure_mailbox(
        self,
        admin_email: str,
        admin_password: str,
        email: str,
        password: str,
        licensed_user_email: str
    ) -> Dict:
        """
        Configure a mailbox:
        - Enable account
        - Set password
        - Fix UPN to match email
        - Setup delegation (FullAccess, SendAs, SendOnBehalf)
        
        Args:
            admin_email: M365 admin email address
            admin_password: M365 admin password
            email: Mailbox email address to configure
            password: Password to set for the mailbox
            licensed_user_email: Email of licensed user to grant delegation
            
        Returns: {
            "success": True/False,
            "email": "...",
            "upn_fixed": True/False,
            "password_set": True/False,
            "delegation_configured": True/False,
            "error": "..." (if any)
        }
        
        Raises:
            PowerShellError: If script execution fails completely
        """
        result = await self.execute_script("configure_mailbox.ps1", {
            "AdminEmail": admin_email,
            "AdminPassword": admin_password,
            "Email": email,
            "Password": password,
            "LicensedUserEmail": licensed_user_email
        })
        
        if result["success"]:
            if isinstance(result["output"], dict):
                return result["output"]
            else:
                return {
                    "success": True,
                    "email": email,
                    "message": str(result["output"])
                }
        else:
            raise PowerShellError(f"Failed to configure mailbox: {result['error']}")
    
    async def test_connection(
        self,
        admin_email: str,
        admin_password: str
    ) -> bool:
        """
        Test Exchange Online PowerShell connection.
        
        Args:
            admin_email: M365 admin email address
            admin_password: M365 admin password
            
        Returns:
            True if connection is successful
        """
        # Simple test - try to get organization config
        cmd = f'''pwsh -NoProfile -NonInteractive -Command "
            $securePassword = ConvertTo-SecureString '{admin_password}' -AsPlainText -Force
            $credential = New-Object System.Management.Automation.PSCredential('{admin_email}', $securePassword)
            try {{
                Connect-ExchangeOnline -Credential $credential -ShowBanner:$false -ErrorAction Stop
                $org = Get-OrganizationConfig
                Disconnect-ExchangeOnline -Confirm:$false
                Write-Output 'success'
            }} catch {{
                Write-Error $_.Exception.Message
                exit 1
            }}
        "'''
        
        try:
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            return process.returncode == 0 and "success" in stdout.decode()
            
        except Exception:
            return False


# Singleton instance for easy import
powershell_service = PowerShellService()


def get_powershell_service() -> PowerShellService:
    """
    Factory function for PowerShellService.
    
    Use this for FastAPI dependency injection:
        @router.post("/dkim")
        async def get_dkim(ps: PowerShellService = Depends(get_powershell_service)):
            ...
    """
    return PowerShellService()