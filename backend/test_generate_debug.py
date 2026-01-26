import asyncio
from uuid import UUID
from app.db.session import SessionLocal
from sqlalchemy import select
from app.models.tenant import Tenant
from app.models.domain import Domain
from app.models.mailbox import Mailbox, MailboxStatus, WarmupStage
from app.services.email_generator import email_generator

async def test_generate():
    tenant_id = UUID('045b7f79-7d56-48b7-b0be-8016c25f9043')
    async with SessionLocal() as db:
        try:
            # Get tenant
            result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
            tenant = result.scalar_one_or_none()
            print(f'Tenant: {tenant.name}')
            print(f'Domain ID: {tenant.domain_id}')
            
            # Get domain
            result = await db.execute(select(Domain).where(Domain.id == tenant.domain_id))
            domain = result.scalar_one_or_none()
            print(f'Domain: {domain.name}')
            
            # Generate emails
            variations = email_generator.generate('Jack', 'Zuvelek', domain.name, 5)
            print(f'Generated {len(variations)} variations:')
            for v in variations:
                print(f'  {v["email"]}')
            
            # Try creating mailbox
            mailbox = Mailbox(
                email=variations[0]['email'],
                display_name=variations[0]['display_name'],
                password=variations[0]['password'],
                tenant_id=tenant_id,
                status=MailboxStatus.PENDING,
                warmup_stage=WarmupStage.NONE,
            )
            print(f'Created mailbox object: {mailbox.email}')
            
            db.add(mailbox)
            await db.commit()
            print('Committed to DB successfully!')
            
        except Exception as e:
            print(f'ERROR: {type(e).__name__}: {e}')
            import traceback
            traceback.print_exc()

asyncio.run(test_generate())