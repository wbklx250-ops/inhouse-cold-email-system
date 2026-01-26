"""
Exchange Online Operations

- DKIM configuration
- Shared mailbox creation
- Delegation setup
"""

import logging
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass

from .runner import powershell, PowerShellResult

logger = logging.getLogger(__name__)


@dataclass
class DkimConfig:
    """DKIM configuration."""
    domain: str
    enabled: bool
    selector1_cname: Optional[str] = None
    selector2_cname: Optional[str] = None


class ExchangeOperations:
    """Exchange Online operations via PowerShell."""
    
    def __init__(self, access_token: str, organization: str):
        self.access_token = access_token
        self.organization = organization
    
    async def _run(self, commands: List[str]) -> PowerShellResult:
        """Run Exchange commands."""
        return await powershell.run_exchange(
            self.access_token,
            self.organization,
            commands
        )
    
    # === DKIM ===
    
    async def init_dkim(self, domain: str) -> DkimConfig:
        """Initialize DKIM for a domain."""
        commands = [
            f'$domain = "{domain}"',
            '',
            '$existing = Get-DkimSigningConfig -Identity $domain -ErrorAction SilentlyContinue',
            '',
            'if (-not $existing) {',
            '    New-DkimSigningConfig -DomainName $domain -Enabled $false | Out-Null',
            '    $existing = Get-DkimSigningConfig -Identity $domain',
            '}',
            '',
            '$result = @{',
            '    Domain = $domain',
            '    Enabled = $existing.Enabled',
            '    Selector1CNAME = $existing.Selector1CNAME',
            '    Selector2CNAME = $existing.Selector2CNAME',
            '}',
            '',
            'Write-Output "<<<JSON>>>"',
            '$result | ConvertTo-Json',
            'Write-Output "<<<END>>>"',
        ]
        
        result = await self._run(commands)
        
        if result.success and result.json_data:
            return DkimConfig(
                domain=domain,
                enabled=result.json_data.get("Enabled", False),
                selector1_cname=result.json_data.get("Selector1CNAME"),
                selector2_cname=result.json_data.get("Selector2CNAME")
            )
        
        raise Exception(f"DKIM init failed: {result.error or result.output}")
    
    async def enable_dkim(self, domain: str) -> bool:
        """Enable DKIM signing."""
        commands = [
            f'Set-DkimSigningConfig -Identity "{domain}" -Enabled $true',
            'Write-Output "DKIM_ENABLED"',
        ]
        
        result = await self._run(commands)
        return result.success and "DKIM_ENABLED" in result.output
    
    # === MAILBOXES ===
    
    async def create_shared_mailbox(self, email: str, display_name: str) -> bool:
        """Create a shared mailbox."""
        commands = [
            f'$email = "{email}"',
            f'$name = "{display_name}"',
            '',
            '$existing = Get-Mailbox -Identity $email -ErrorAction SilentlyContinue',
            '',
            'if (-not $existing) {',
            '    $tempName = "$name $(Get-Random -Maximum 9999)"',
            '    New-Mailbox -Shared -Name $tempName -DisplayName $name -PrimarySmtpAddress $email | Out-Null',
            '    Start-Sleep -Seconds 3',
            '    Set-Mailbox -Identity $email -DisplayName $name -Name $name -ErrorAction SilentlyContinue',
            '}',
            '',
            'Write-Output "MAILBOX_CREATED"',
        ]
        
        result = await self._run(commands)
        return result.success and "MAILBOX_CREATED" in result.output
    
    async def add_full_access(self, mailbox: str, delegate: str) -> bool:
        """Add FullAccess permission."""
        commands = [
            f'Add-MailboxPermission -Identity "{mailbox}" -User "{delegate}" -AccessRights FullAccess -InheritanceType All -AutoMapping $false | Out-Null',
            'Write-Output "PERMISSION_ADDED"',
        ]
        
        result = await self._run(commands)
        return result.success
    
    async def add_send_as(self, mailbox: str, delegate: str) -> bool:
        """Add SendAs permission."""
        commands = [
            f'Add-RecipientPermission -Identity "{mailbox}" -Trustee "{delegate}" -AccessRights SendAs -Confirm:$false | Out-Null',
            'Write-Output "SENDAS_ADDED"',
        ]
        
        result = await self._run(commands)
        return result.success
    
    async def create_and_delegate_mailbox(
        self,
        email: str,
        display_name: str,
        delegate: str
    ) -> bool:
        """Create mailbox and set up full delegation."""
        commands = [
            f'$email = "{email}"',
            f'$name = "{display_name}"',
            f'$delegate = "{delegate}"',
            '',
            '# Create if not exists',
            '$existing = Get-Mailbox -Identity $email -ErrorAction SilentlyContinue',
            'if (-not $existing) {',
            '    $tempName = "$name $(Get-Random -Maximum 9999)"',
            '    New-Mailbox -Shared -Name $tempName -DisplayName $name -PrimarySmtpAddress $email | Out-Null',
            '    Start-Sleep -Seconds 3',
            '    Set-Mailbox -Identity $email -DisplayName $name -Name $name -ErrorAction SilentlyContinue',
            '}',
            '',
            '# Add permissions',
            'Add-MailboxPermission -Identity $email -User $delegate -AccessRights FullAccess -InheritanceType All -AutoMapping $false -ErrorAction SilentlyContinue | Out-Null',
            'Add-RecipientPermission -Identity $email -Trustee $delegate -AccessRights SendAs -Confirm:$false -ErrorAction SilentlyContinue | Out-Null',
            '',
            'Write-Output "COMPLETE"',
        ]
        
        result = await self._run(commands)
        return result.success and "COMPLETE" in result.output