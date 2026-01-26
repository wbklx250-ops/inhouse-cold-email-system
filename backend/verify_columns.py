"""Verify domain columns exist in Neon database."""
import asyncio
from sqlalchemy import text
from app.db.session import engine


async def check_columns():
    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'domains' 
            ORDER BY column_name
        """))
        print("DOMAINS TABLE COLUMNS:")
        for row in result.fetchall():
            print(f"  - {row[0]}")
        
        # Check for specific new columns
        new_columns = [
            'phase1_cname_added',
            'phase1_dmarc_added', 
            'verification_txt_value',
            'verification_txt_added',
            'error_message',
            'ns_propagated_at',
            'm365_verified_at'
        ]
        
        result = await conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'domains' 
            AND column_name = ANY(:cols)
        """), {"cols": new_columns})
        
        found = [row[0] for row in result.fetchall()]
        print("\nNEW COLUMNS CHECK:")
        for col in new_columns:
            status = "✅" if col in found else "❌"
            print(f"  {status} {col}")


if __name__ == "__main__":
    asyncio.run(check_columns())