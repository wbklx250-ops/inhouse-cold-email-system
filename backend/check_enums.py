import asyncio
from app.db.session import SessionLocal
from sqlalchemy import text

async def check_enums():
    async with SessionLocal() as db:
        result = await db.execute(text("""
            SELECT e.enumlabel 
            FROM pg_enum e
            JOIN pg_type t ON e.enumtypid = t.oid
            WHERE t.typname = 'mailbox_status'
            ORDER BY e.enumsortorder
        """))
        print('Current mailbox_status enum values in DB:')
        for row in result.fetchall():
            print(f'  - {row[0]}')

asyncio.run(check_enums())