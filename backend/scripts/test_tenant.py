"""
Test Single Tenant Automation

Usage:
    python -m scripts.test_tenant --step login
    python -m scripts.test_tenant --step all
"""

import asyncio
import argparse
import logging

logging.basicConfig(level=logging.INFO)

# Test tenant
TEST_TENANT = {
    "id": "be06745b-d4a7-4641-8289-88bef7ee600a",
    "admin_email": "admin@Quopharamonquo9360193.onmicrosoft.com",
    "password": "v+YRt3hd",
    "onmicrosoft": "Quopharamonquo9360193.onmicrosoft.com"
}


async def test_login():
    """Test first login automation."""
    from app.services.selenium import MicrosoftLoginAutomation
    
    print("\n=== Testing First Login ===")
    print(f"Email: {TEST_TENANT['admin_email']}")
    
    automation = MicrosoftLoginAutomation(headless=False)  # Show browser
    
    result = await automation.complete_first_login(
        admin_email=TEST_TENANT["admin_email"],
        initial_password=TEST_TENANT["password"],
        new_password="NewTestPassword123!",
        existing_totp=None
    )
    
    print(f"\nResult:")
    print(f"  Success: {result.success}")
    print(f"  New Password: {result.new_password}")
    print(f"  TOTP Secret: {result.totp_secret}")
    print(f"  Security Defaults: {result.security_defaults_disabled}")
    print(f"  Error: {result.error}")
    print(f"  Screenshots: {result.screenshots}")
    
    return result


async def test_oauth():
    """Test OAuth token acquisition."""
    from app.services.microsoft import DeviceCodeAuth
    
    print("\n=== Testing OAuth ===")
    
    auth = DeviceCodeAuth()
    tokens = await auth.get_tokens(
        tenant_id=TEST_TENANT["id"],
        admin_email=TEST_TENANT["admin_email"],
        admin_password=TEST_TENANT["password"],
        headless=False
    )
    
    if tokens:
        print(f"Access Token: {tokens.access_token[:50]}...")
        print(f"Expires: {tokens.expires_at}")
    else:
        print("Failed to get tokens")
    
    return tokens


async def test_graph(access_token: str):
    """Test Graph API."""
    from app.services.microsoft import GraphClient
    
    print("\n=== Testing Graph API ===")
    
    graph = GraphClient(access_token)
    
    domains = await graph.list_domains()
    print(f"Domains: {[d.id for d in domains]}")
    
    licenses = await graph.list_licenses()
    print(f"Licenses: {licenses}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", choices=["login", "oauth", "graph", "all"], default="login")
    args = parser.parse_args()
    
    if args.step in ["login", "all"]:
        result = await test_login()
        
        if args.step == "all" and result.success:
            tokens = await test_oauth()
            if tokens:
                await test_graph(tokens.access_token)
    
    elif args.step == "oauth":
        await test_oauth()


if __name__ == "__main__":
    asyncio.run(main())