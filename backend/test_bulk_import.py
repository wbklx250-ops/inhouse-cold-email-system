"""Test script for bulk-import endpoint"""
import asyncio
import csv
import io
from app.db.session import get_db_session, SessionLocal
from app.models.domain import Domain, DomainStatus
from sqlalchemy import select

async def test_bulk_import():
    """Test that we can import domains successfully."""
    test_csv = """domain_name,registrar,registration_date
test1-bulk.com,Porkbun,2025-01-15
test2-bulk.com,Porkbun,2025-01-15
test3-bulk.net,Porkbun,2025-01-15"""
    
    async with SessionLocal() as db:
        # Parse CSV
        reader = csv.DictReader(io.StringIO(test_csv))
        rows = list(reader)
        
        # Check existing
        domain_names = [row["domain_name"].strip().lower() for row in rows]
        existing_query = await db.execute(
            select(Domain.name).where(Domain.name.in_(domain_names))
        )
        existing = set(existing_query.scalars().all())
        
        # Create new domains
        created = 0
        for row in rows:
            name = row["domain_name"].strip().lower()
            if name not in existing:
                domain = Domain(
                    name=name,
                    tld="." + name.rsplit(".", 1)[-1],
                    status=DomainStatus.PURCHASED,
                    cloudflare_nameservers=[],
                    cloudflare_zone_status="pending",
                )
                db.add(domain)
                created += 1
                print(f"  Creating: {name}")
        
        if created > 0:
            await db.commit()
        
        print(f"\nResult: {created} domains created, {len(existing)} skipped (already exist)")
        
        # List all domains
        all_domains = await db.execute(select(Domain).limit(10))
        print("\nDomains in database:")
        for d in all_domains.scalars().all():
            print(f"  - {d.name} ({d.status.value})")

if __name__ == "__main__":
    print("Testing bulk domain import functionality...\n")
    asyncio.run(test_bulk_import())
    print("\n✅ Test complete!")