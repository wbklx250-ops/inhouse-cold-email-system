"""Direct Cloudflare API test - bypass all app code"""
import httpx
import os
import sys

# Load credentials from .env
email = None
key = None
for env_path in [".env", "../.env", "backend/.env"]:
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("CLOUDFLARE_EMAIL="):
                    email = line.split("=", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("CLOUDFLARE_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
        if email and key:
            break
    except:
        continue

print(f"Email: {email}")
print(f"API Key: {key[:10]}...{key[-5:]}" if key else "API Key: MISSING")

headers = {"X-Auth-Email": email, "X-Auth-Key": key, "Content-Type": "application/json"}

# Step 1: List zones
print("\n=== LISTING ZONES ===")
resp = httpx.get("https://api.cloudflare.com/client/v4/zones?per_page=5", headers=headers, timeout=30)
print(f"HTTP Status: {resp.status_code}")
data = resp.json()
print(f"API success: {data.get('success')}")
print(f"Errors: {data.get('errors')}")

zones = data.get("result", [])
if not zones:
    print("NO ZONES FOUND - credentials may be wrong!")
    sys.exit(1)

for z in zones[:5]:
    print(f"  Zone: {z['name']} -> {z['id']}")

# Use the zone from the logs
test_zone_id = "6fca1780aceeee93369bc7bc46100a31"
print(f"\n=== TESTING ZONE {test_zone_id} ===")

# Step 2: List existing TXT records
print("\n--- Existing TXT records ---")
resp = httpx.get(f"https://api.cloudflare.com/client/v4/zones/{test_zone_id}/dns_records?type=TXT", headers=headers, timeout=30)
print(f"HTTP Status: {resp.status_code}")
data = resp.json()
print(f"API success: {data.get('success')}")
print(f"Errors: {data.get('errors')}")
for r in data.get("result", []):
    print(f"  TXT: {r.get('name')} -> {r.get('content')[:80]} (id={r.get('id')})")

# Step 3: Try to add a test TXT record
test_value = "MS=ms_TEST_12345"
print(f"\n--- Adding test TXT: {test_value} ---")
resp = httpx.post(f"https://api.cloudflare.com/client/v4/zones/{test_zone_id}/dns_records", 
                   headers=headers,
                   json={"type": "TXT", "name": "@", "content": test_value, "ttl": 1},
                   timeout=30)
print(f"HTTP Status: {resp.status_code}")
data = resp.json()
print(f"API success: {data.get('success')}")
print(f"Errors: {data.get('errors')}")
if data.get("result"):
    print(f"Record ID: {data['result'].get('id')}")
    print(f"Content: {data['result'].get('content')}")

# Step 4: Verify it exists
print(f"\n--- Verifying TXT record exists ---")
resp = httpx.get(f"https://api.cloudflare.com/client/v4/zones/{test_zone_id}/dns_records?type=TXT", headers=headers, timeout=30)
data = resp.json()
found = False
for r in data.get("result", []):
    if test_value in r.get("content", ""):
        print(f"  FOUND: {r.get('name')} -> {r.get('content')} (id={r.get('id')})")
        found = True
        # Clean up - delete it
        del_resp = httpx.delete(f"https://api.cloudflare.com/client/v4/zones/{test_zone_id}/dns_records/{r['id']}", headers=headers, timeout=30)
        print(f"  Cleanup delete: HTTP {del_resp.status_code}, success={del_resp.json().get('success')}")

if not found:
    print("  NOT FOUND! Record was NOT actually created despite API saying success!")
    print("  This confirms the Cloudflare API is lying about success!")
