"""
Graph API Authentication using ROPC Flow

Uses admin credentials already stored in database.
No manual setup required.
"""

import aiohttp
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Microsoft's public client IDs that support ROPC
# Azure PowerShell - widely used, supports ROPC
AZURE_POWERSHELL_CLIENT_ID = "1950a258-227b-4e31-a9cf-717495945fc2"

# Alternative: Azure CLI client ID
AZURE_CLI_CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"


async def get_graph_token_ropc(
    admin_email: str,
    admin_password: str,
    client_id: str = AZURE_POWERSHELL_CLIENT_ID,
) -> Optional[str]:
    """
    Get Microsoft Graph API token using Resource Owner Password Credentials flow.

    This uses the admin credentials we already have stored - no setup needed.

    Args:
        admin_email: Admin email (e.g., admin@tenant.onmicrosoft.com)
        admin_password: Admin password
        client_id: Public client ID to use (default: Azure PowerShell)

    Returns:
        Access token string or None if failed
    """
    if "@" not in admin_email:
        logger.error("Invalid admin email format: %s", admin_email)
        return None

    tenant_domain = admin_email.split("@", 1)[1]
    token_url = f"https://login.microsoftonline.com/{tenant_domain}/oauth2/v2.0/token"

    payload = {
        "grant_type": "password",
        "client_id": client_id,
        "scope": "https://graph.microsoft.com/.default offline_access",
        "username": admin_email,
        "password": admin_password,
    }

    logger.info("Requesting Graph token via ROPC for %s", admin_email)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                token_url,
                data=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                response_text = await response.text()

                if response.status == 200:
                    data = await response.json()
                    token = data.get("access_token")
                    if token:
                        logger.info(
                            "✓ Graph token obtained via ROPC, length: %s",
                            len(token),
                        )
                        return token
                    logger.error("Token response missing access_token field")
                    return None

                logger.error(
                    "ROPC token request failed (%s): %s",
                    response.status,
                    response_text,
                )

                if client_id == AZURE_POWERSHELL_CLIENT_ID:
                    logger.info("Retrying with Azure CLI client ID...")
                    return await get_graph_token_ropc(
                        admin_email,
                        admin_password,
                        AZURE_CLI_CLIENT_ID,
                    )

                return None

    except aiohttp.ClientError as exc:
        logger.error("HTTP error during ROPC auth: %s", exc)
        return None
    except Exception as exc:
        logger.error("Unexpected error during ROPC auth: %s", exc)
        return None


def get_graph_token_ropc_sync(admin_email: str, admin_password: str) -> Optional[str]:
    """Synchronous wrapper for get_graph_token_ropc."""
    import asyncio

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(get_graph_token_ropc(admin_email, admin_password))
    finally:
        loop.close()


if __name__ == "__main__":
    import asyncio
    import sys

    logging.basicConfig(level=logging.INFO)

    print("=" * 60)
    print("ROPC TOKEN TEST")
    print("=" * 60)

    if len(sys.argv) != 3:
        print("Usage: python graph_auth.py <admin_email> <admin_password>")
        sys.exit(1)

    email = sys.argv[1]
    password = sys.argv[2]

    print(f"\nTesting ROPC for: {email}")

    async def test():
        token = await get_graph_token_ropc(email, password)
        if token:
            print(f"\n✓ SUCCESS! Token length: {len(token)}")
            print(f"Token preview: {token[:50]}...")
        else:
            print("\n✗ FAILED to get token")

    asyncio.run(test())