from __future__ import annotations

from io import StringIO
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.domain import Domain
from app.models.mailbox import Mailbox, MailboxStatus, WarmupStage
from app.models.tenant import Tenant, TenantStatus
from app.schemas.mailbox import MailboxCreate, MailboxRead, MailboxUpdate
from app.services.email_generator import generate_email_addresses

router = APIRouter(prefix="/api/v1/mailboxes", tags=["mailboxes"])


class MailboxGenerateRequest(BaseModel):
    tenant_id: UUID
    first_name: str
    last_name: str
    count: int = 50


class PersonaBase(BaseModel):
    first_name: str
    last_name: str


async def get_mailbox_or_404(mailbox_id: UUID, db: AsyncSession) -> Mailbox:
    """Get mailbox by ID or raise 404."""
    result = await db.execute(select(Mailbox).where(Mailbox.id == mailbox_id))
    mailbox = result.scalar_one_or_none()
    if not mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    return mailbox


@router.get("/", response_model=list[MailboxRead])
async def list_mailboxes(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    tenant_id: UUID | None = Query(default=None),
    status: MailboxStatus | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[Mailbox]:
    """List all mailboxes with optional filters."""
    query = select(Mailbox)
    if tenant_id:
        query = query.where(Mailbox.tenant_id == tenant_id)
    if status:
        query = query.where(Mailbox.status == status)
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("/", response_model=MailboxRead, status_code=201)
async def create_mailbox(
    mailbox_in: MailboxCreate,
    db: AsyncSession = Depends(get_db),
) -> Mailbox:
    """Create a single mailbox."""
    # Check if email already exists
    existing = await db.execute(select(Mailbox).where(Mailbox.email == mailbox_in.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already exists")

    # Verify tenant exists
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == mailbox_in.tenant_id))
    if not tenant_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Tenant not found")

    mailbox = Mailbox(
        email=mailbox_in.email,
        display_name=mailbox_in.display_name,
        password=mailbox_in.password,
        tenant_id=mailbox_in.tenant_id,
        status=MailboxStatus.PENDING,
        warmup_stage=WarmupStage.NONE,
    )
    db.add(mailbox)
    await db.commit()
    await db.refresh(mailbox)
    return mailbox


@router.post("/generate")
async def generate_mailboxes(
    request: MailboxGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate mailbox records for a tenant.
    Creates records in DATABASE only - not in M365 yet.
    
    Steps:
    1. Validate tenant exists and has a linked domain
    2. Get domain name from linked domain
    3. Generate email variations using email_generator
       - NO NUMBERS in emails
       - Display name is the same for all (e.g., "Jack Zuvelek")
       - Each gets a unique secure password
    4. Create mailbox records in DB with status="pending"
    5. Return generated list
    
    Returns: {
        "tenant_id": "...",
        "domain": "example.com",
        "mailboxes_generated": 50,
        "mailboxes": [
            {"email": "jack.zuvelek@example.com", "display_name": "Jack Zuvelek", "password": "xK9#mP2$"},
            ...
        ]
    }
    """
    # Verify tenant exists and get associated domain
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == request.tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Get domain for this tenant
    if not tenant.domain_id:
        raise HTTPException(status_code=400, detail="Tenant has no linked domain")

    domain_result = await db.execute(select(Domain).where(Domain.id == tenant.domain_id))
    domain = domain_result.scalar_one_or_none()
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")

    # Generate email variations using the new generator (NO NUMBERS!)
    variations = generate_email_addresses(
        first_name=request.first_name,
        last_name=request.last_name,
        domain=domain.name,
        count=request.count,
    )

    created_mailboxes: list[dict] = []

    for var in variations:
        # Check if email already exists
        existing = await db.execute(select(Mailbox).where(Mailbox.email == var["email"]))
        if existing.scalar_one_or_none():
            continue

        mailbox = Mailbox(
            email=var["email"],
            display_name=var["display_name"],
            password=var["password"],
            tenant_id=request.tenant_id,
            status=MailboxStatus.PENDING,
            warmup_stage=WarmupStage.NONE,
        )
        db.add(mailbox)
        created_mailboxes.append({
            "email": var["email"],
            "display_name": var["display_name"],
            "password": var["password"],
        })

    await db.commit()

    return {
        "tenant_id": str(request.tenant_id),
        "domain": domain.name,
        "mailboxes_generated": len(created_mailboxes),
        "mailboxes": created_mailboxes,
    }


@router.post("/bulk-create-in-m365")
async def bulk_create_mailboxes_in_m365(
    tenant_ids: Optional[List[UUID]] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Create pending mailboxes in M365.
    
    If tenant_ids is None, process all tenants with pending mailboxes and dkim_enabled.
    
    For EACH tenant:
    1. Get all mailboxes with status="pending"
    2. Get admin credentials from tenant
    3. Call PowerShell to create shared mailboxes in M365
    4. Update each mailbox with microsoft_object_id
    5. Update status="created"
    6. Update tenant.mailboxes_created count
    
    Returns: Summary of results
    """
    from app.services.powershell import powershell_service
    
    results = {
        "tenants_processed": 0,
        "mailboxes_created": 0,
        "errors": [],
    }
    
    # Build query for tenants
    tenant_query = select(Tenant)
    if tenant_ids:
        tenant_query = tenant_query.where(Tenant.id.in_(tenant_ids))
    else:
        # Only process tenants with DKIM enabled
        tenant_query = tenant_query.where(Tenant.status == TenantStatus.DKIM_ENABLED)
    
    tenant_result = await db.execute(tenant_query)
    tenants = list(tenant_result.scalars().all())
    
    for tenant in tenants:
        # Get pending mailboxes for this tenant
        mailbox_query = select(Mailbox).where(
            Mailbox.tenant_id == tenant.id,
            Mailbox.status == MailboxStatus.PENDING,
        )
        mailbox_result = await db.execute(mailbox_query)
        mailboxes = list(mailbox_result.scalars().all())
        
        if not mailboxes:
            continue
        
        try:
            # Build mailbox list for PowerShell script
            mailbox_list = [
                {"email": mb.email, "display_name": mb.display_name}
                for mb in mailboxes
            ]
            
            # Call PowerShell to create mailboxes
            ps_results = await powershell_service.create_shared_mailboxes(
                admin_email=tenant.admin_email,
                admin_password=tenant.admin_password,
                mailboxes=mailbox_list,
            )
            
            # Update mailboxes with results
            for created in ps_results:
                email = created.get("email")
                object_id = created.get("object_id")
                success = created.get("success", False)
                
                # Find matching mailbox
                for mb in mailboxes:
                    if mb.email.lower() == email.lower():
                        if success:
                            mb.microsoft_object_id = object_id
                            mb.status = MailboxStatus.CREATED
                            results["mailboxes_created"] += 1
                        else:
                            mb.status = MailboxStatus.ERROR
                            mb.error_message = created.get("error", "Unknown error")
                        break
            
            # Update tenant count
            tenant.mailboxes_created += results["mailboxes_created"]
            tenant.status = TenantStatus.MAILBOXES_CREATING
            results["tenants_processed"] += 1
                
        except Exception as e:
            results["errors"].append({
                "tenant_id": str(tenant.id),
                "error": str(e),
            })
    
    await db.commit()
    return results


@router.post("/bulk-configure")
async def bulk_configure_mailboxes(
    tenant_ids: Optional[List[UUID]] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Configure created mailboxes (enable, password, UPN, delegation).
    
    For EACH tenant:
    1. Get all mailboxes with status="created"
    2. Get admin credentials and licensed_user_upn from tenant
    3. For each mailbox:
       a. Enable account
       b. Set password (from mailbox.password field)
       c. Fix UPN to match email
       d. Setup delegation to licensed user
    4. Update mailbox status="ready"
    5. Update tenant.mailboxes_configured count
    
    Returns: Summary of results
    """
    from app.services.powershell import powershell_service
    
    results = {
        "tenants_processed": 0,
        "mailboxes_configured": 0,
        "errors": [],
    }
    
    # Build query for tenants
    tenant_query = select(Tenant)
    if tenant_ids:
        tenant_query = tenant_query.where(Tenant.id.in_(tenant_ids))
    else:
        # Only process tenants in mailboxes_creating state
        tenant_query = tenant_query.where(
            Tenant.status.in_([TenantStatus.MAILBOXES_CREATING, TenantStatus.DKIM_ENABLED])
        )
    
    tenant_result = await db.execute(tenant_query)
    tenants = list(tenant_result.scalars().all())
    
    for tenant in tenants:
        # Get created mailboxes for this tenant
        mailbox_query = select(Mailbox).where(
            Mailbox.tenant_id == tenant.id,
            Mailbox.status == MailboxStatus.CREATED,
        )
        mailbox_result = await db.execute(mailbox_query)
        mailboxes = list(mailbox_result.scalars().all())
        
        if not mailboxes:
            continue
        
        configured_count = 0
        
        for mailbox in mailboxes:
            try:
                # Call PowerShell to configure mailbox
                ps_result = await powershell_service.configure_mailbox(
                    admin_email=tenant.admin_email,
                    admin_password=tenant.admin_password,
                    email=mailbox.email,
                    password=mailbox.password,
                    licensed_user_upn=tenant.licensed_user_upn,
                )
                
                if ps_result.get("success"):
                    # Update mailbox state
                    # Note: configure_mailbox enables the account as part of its flow
                    mailbox.account_enabled = True
                    mailbox.password_set = ps_result.get("password_set", False)
                    mailbox.upn_fixed = ps_result.get("upn_fixed", False)
                    mailbox.delegated = ps_result.get("delegation_configured", False)
                    
                    # If all steps complete, mark as ready
                    if all([
                        mailbox.account_enabled,
                        mailbox.password_set,
                        mailbox.upn_fixed,
                        mailbox.delegated,
                    ]):
                        mailbox.status = MailboxStatus.READY
                        configured_count += 1
                        results["mailboxes_configured"] += 1
                    else:
                        # Partial configuration
                        mailbox.status = MailboxStatus.CONFIGURED
                else:
                    error_msg = ps_result.get("error", "Unknown error")
                    mailbox.status = MailboxStatus.ERROR
                    mailbox.error_message = error_msg
                    results["errors"].append({
                        "mailbox_email": mailbox.email,
                        "error": error_msg,
                    })
                    
            except Exception as e:
                mailbox.status = MailboxStatus.ERROR
                mailbox.error_message = str(e)
                results["errors"].append({
                    "mailbox_email": mailbox.email,
                    "error": str(e),
                })
        
        # Update tenant counts
        tenant.mailboxes_configured += configured_count
        if configured_count > 0:
            tenant.status = TenantStatus.MAILBOXES_CONFIGURING
        if tenant.mailboxes_configured >= tenant.mailboxes_created:
            tenant.status = TenantStatus.ACTIVE
        results["tenants_processed"] += 1
    
    await db.commit()
    return results


@router.get("/export-credentials")
async def export_credentials(
    tenant_id: Optional[UUID] = None,
    format: str = "csv",
    db: AsyncSession = Depends(get_db),
):
    """
    Export mailbox credentials as CSV download.
    
    CSV format (matches your existing format):
    DisplayName,EmailAddress,Password
    Jack Zuvelek,jack@example.com,xK9#mP2$vL
    Jack Zuvelek,j.zuvelek@example.com,Abc123!@#
    
    If tenant_id provided, export only that tenant's mailboxes.
    Otherwise export all ready mailboxes.
    """
    # Query mailboxes
    query = select(Mailbox).where(Mailbox.status == MailboxStatus.READY)
    if tenant_id:
        query = query.where(Mailbox.tenant_id == tenant_id)
    
    result = await db.execute(query)
    mailboxes = result.scalars().all()
    
    # Generate CSV
    output = StringIO()
    output.write("DisplayName,EmailAddress,Password\n")
    for mb in mailboxes:
        output.write(f"{mb.display_name},{mb.email},{mb.password or '#Sendemails1'}\n")
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=mailbox_credentials.csv"}
    )


@router.get("/export")
async def export_mailbox_credentials(
    tenant_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Export mailbox credentials as CSV (legacy endpoint).
    Returns email,password columns.
    """
    query = select(Mailbox)
    if tenant_id:
        query = query.where(Mailbox.tenant_id == tenant_id)
    result = await db.execute(query)
    mailboxes = list(result.scalars().all())

    # Build CSV
    output = StringIO()
    output.write("email,password\n")
    for mailbox in mailboxes:
        output.write(f"{mailbox.email},{mailbox.password or '#Sendemails1'}\n")

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=mailbox_credentials.csv"},
    )


@router.get("/{mailbox_id}", response_model=MailboxRead)
async def get_mailbox(
    mailbox_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> Mailbox:
    """Get a single mailbox by ID."""
    return await get_mailbox_or_404(mailbox_id, db)


@router.patch("/{mailbox_id}", response_model=MailboxRead)
async def update_mailbox(
    mailbox_id: UUID,
    mailbox_in: MailboxUpdate,
    db: AsyncSession = Depends(get_db),
) -> Mailbox:
    """Update mailbox fields."""
    mailbox = await get_mailbox_or_404(mailbox_id, db)

    update_data = mailbox_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(mailbox, field, value)

    await db.commit()
    await db.refresh(mailbox)
    return mailbox


@router.delete("/{mailbox_id}")
async def delete_mailbox(
    mailbox_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Soft delete mailbox by setting status to suspended."""
    mailbox = await get_mailbox_or_404(mailbox_id, db)
    mailbox.status = MailboxStatus.SUSPENDED
    await db.commit()
    return {"message": "Mailbox suspended"}