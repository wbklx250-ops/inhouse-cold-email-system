from .auth import DeviceCodeAuth, TokenResponse
from .graph import GraphClient, DomainInfo, DnsRecord


class MicrosoftGraphError(Exception):
    """Custom exception for Microsoft Graph API errors."""
    pass


# Alias for backwards compatibility
MicrosoftGraphService = GraphClient

__all__ = [
    "DeviceCodeAuth",
    "TokenResponse",
    "GraphClient",
    "DomainInfo",
    "DnsRecord",
    "MicrosoftGraphService",
    "MicrosoftGraphError",
]