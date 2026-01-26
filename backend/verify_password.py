"""Verify that admin_password is stored as plain text for CSV import."""
import asyncio
from sqlalchemy import select, text
from app.db.session import engine

async def check_passwords():
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT name, admin_password FROM tenants WHERE name LIKE 'Test Tenant%' ORDER BY name LIMIT 3")
        )
        rows = result.fetchall()
        print("\n=== Tenants from CSV Import (Password Storage Check) ===")
        for row in rows:
            name, password = row
            print(f"  {name}: password = '{password}'")
        
        # Check if plain text (not base64)
        print("\n=== Verification ===")
        for row in rows:
            name, password = row
            is_plain = not (password.endswith('=') or password.endswith('=='))
            print(f"  {name}: {'PLAIN TEXT ✓' if is_plain else 'BASE64 (needs fix)'}")

if __name__ == "__main__":
    asyncio.run(check_passwords())