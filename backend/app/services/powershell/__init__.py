"""
PowerShell Services Package

Provides PowerShell Core execution capabilities for Exchange Online operations.
Includes auto-installation of required PowerShell modules on startup.
"""

from .runner import PowerShellRunner, PowerShellResult, powershell, PWSH_PATH
from .exchange import ExchangeOperations, DkimConfig
from .setup import (
    ensure_powershell_modules,
    get_module_status,
    check_powershell_available,
    REQUIRED_MODULES
)


class PowerShellError(Exception):
    """Custom exception for PowerShell execution errors."""
    pass


# Alias for backwards compatibility
PowerShellService = PowerShellRunner
powershell_service = powershell


def get_powershell_service() -> PowerShellRunner:
    """Factory function for PowerShell service."""
    return powershell


__all__ = [
    # Core runner
    "PowerShellRunner",
    "PowerShellResult", 
    "powershell",
    "PWSH_PATH",
    # Exchange operations
    "ExchangeOperations",
    "DkimConfig",
    # Setup/installation
    "ensure_powershell_modules",
    "get_module_status",
    "check_powershell_available",
    "REQUIRED_MODULES",
    # Aliases
    "PowerShellService",
    "PowerShellError",
    "powershell_service",
    "get_powershell_service",
]