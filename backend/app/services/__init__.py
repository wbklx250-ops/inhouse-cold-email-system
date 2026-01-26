from app.services.cloudflare import CloudflareError, CloudflareService
from app.services.mailbox_scripts import MailboxScriptGenerator, mailbox_scripts
from app.services.powershell import (
    PowerShellRunner,
    PowerShellResult,
    powershell,
    PWSH_PATH,
    ExchangeOperations,
    DkimConfig,
)
from app.services.orchestrator import (
    SetupStep,
    SetupConfig,
    SetupResult,
    TenantSetupOrchestrator,
    process_batch,
)


def get_cloudflare_service() -> CloudflareService:
    """
    Factory function for CloudflareService.
    
    Use this for FastAPI dependency injection:
        @router.post("/domains")
        async def create_domain(cf: CloudflareService = Depends(get_cloudflare_service)):
            ...
    """
    return CloudflareService()


__all__ = [
    # Cloudflare
    "CloudflareError",
    "CloudflareService",
    "get_cloudflare_service",
    # Mailbox Scripts
    "MailboxScriptGenerator",
    "mailbox_scripts",
    # PowerShell
    "PowerShellRunner",
    "PowerShellResult",
    "powershell",
    "PWSH_PATH",
    "ExchangeOperations",
    "DkimConfig",
    # Orchestrator
    "SetupStep",
    "SetupConfig",
    "SetupResult",
    "TenantSetupOrchestrator",
    "process_batch",
]