"""
Tenant Import Service

Parses and merges:
- Tenant List CSV (Company info, UUIDs)
- Credentials TXT (Admin emails + passwords)

IMPORTANT: Files are NOT in the same order - matching is done by onmicrosoft domain.
"""

import csv
import io
import re
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.tenant import Tenant, TenantStatus
from app.models.domain import Domain


@dataclass
class CredentialData:
    """Credential data extracted from TXT file."""
    email: str
    password: str
    onmicrosoft_domain: str  # The domain part for matching


class TenantImportService:
    """Import tenants from reseller files."""
    
    def _extract_onmicrosoft_domain(self, text: str) -> Optional[str]:
        """
        Extract onmicrosoft domain from email or domain string.
        
        Examples:
        - "admin@acmecorp123.onmicrosoft.com" -> "acmecorp123.onmicrosoft.com"
        - "acmecorp123.onmicrosoft.com" -> "acmecorp123.onmicrosoft.com"
        - "acmecorp123" -> "acmecorp123.onmicrosoft.com" (prefix only)
        """
        text = text.strip().lower()
        
        # Try to extract full onmicrosoft.com domain
        match = re.search(r'([a-zA-Z0-9-]+\.onmicrosoft\.com)', text, re.IGNORECASE)
        if match:
            return match.group(1).lower()
        
        # If it looks like just a prefix (no dots, no @), add .onmicrosoft.com
        if text and '@' not in text and '.' not in text:
            return f"{text}.onmicrosoft.com"
        
        return None
    
    def parse_tenant_csv(self, csv_content: str) -> List[Dict[str, str]]:
        """
        Parse tenant list CSV.
        
        Expected columns:
        - Company Name
        - onmicrosoft (prefix only)
        - Address
        - Admin Name (contact, not M365 admin)
        - Admin Email (contact gmail)
        - Admin Phone
        - UUID (Tenant ID)
        """
        # Handle BOM
        csv_content = csv_content.replace('\ufeff', '')
        
        reader = csv.DictReader(io.StringIO(csv_content))
        tenants = []
        
        for row in reader:
            clean = {k.strip(): v.strip() for k, v in row.items()}
            
            # Extract onmicrosoft domain (handle both prefix and full domain)
            onmicrosoft_raw = clean.get("onmicrosoft", "")
            onmicrosoft_domain = self._extract_onmicrosoft_domain(onmicrosoft_raw)
            
            if not onmicrosoft_domain:
                # Try to find it in any column
                for value in clean.values():
                    if value and 'onmicrosoft' in value.lower():
                        onmicrosoft_domain = self._extract_onmicrosoft_domain(value)
                        if onmicrosoft_domain:
                            break
            
            tenant = {
                "company_name": clean.get("Company Name", ""),
                "onmicrosoft_domain": onmicrosoft_domain or "",
                "address": clean.get("Address", ""),
                "contact_name": clean.get("Admin Name", ""),
                "contact_email": clean.get("Admin Email", ""),
                "contact_phone": clean.get("Admin Phone", ""),
                "tenant_id": clean.get("UUID", ""),
            }
            
            if tenant["company_name"] and tenant["onmicrosoft_domain"]:
                tenants.append(tenant)
        
        return tenants
    
    def parse_credentials_txt(self, txt_content: str) -> Dict[str, CredentialData]:
        """
        Parse credentials TXT file.
        
        Supports TWO formats:
        
        1. Tab-separated (legacy):
           Username<TAB>Password
           admin@xxx.onmicrosoft.com<TAB>P@ssw0rd
        
        2. Line-pair format:
           admin@company1.onmicrosoft.com
           Password123
           admin@company2.onmicrosoft.com
           Password456
        
        Returns: Dict mapping onmicrosoft_domain -> CredentialData
        """
        credentials = {}
        lines = [line.strip() for line in txt_content.strip().split('\n')]
        
        # Filter out empty lines and header
        lines = [l for l in lines if l and not l.lower().startswith('username')]
        
        # Detect format: if first non-empty line has tab, it's tab-separated
        is_tab_separated = any('\t' in line for line in lines[:5])
        
        if is_tab_separated:
            # Tab-separated format
            for line in lines:
                parts = line.split('\t')
                if len(parts) >= 2:
                    email = parts[0].strip()
                    password = parts[1].strip()
                    
                    domain = self._extract_onmicrosoft_domain(email)
                    if domain and email and password:
                        credentials[domain] = CredentialData(
                            email=email,
                            password=password,
                            onmicrosoft_domain=domain
                        )
        else:
            # Line-pair format (email on one line, password on next)
            i = 0
            while i < len(lines) - 1:
                email = lines[i]
                password = lines[i + 1]
                
                # Check if this looks like an email (contains @)
                if '@' in email and 'onmicrosoft.com' in email.lower():
                    domain = self._extract_onmicrosoft_domain(email)
                    if domain:
                        credentials[domain] = CredentialData(
                            email=email,
                            password=password,
                            onmicrosoft_domain=domain
                        )
                    i += 2  # Move to next pair
                else:
                    i += 1  # Skip this line, try next
        
        return credentials
    
    def merge_data(
        self,
        tenant_list: List[Dict[str, str]],
        credentials: Dict[str, CredentialData]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]], List[str]]:
        """
        Merge tenant list with credentials by onmicrosoft domain.
        
        IMPORTANT: Matches by domain, NOT by row position.
        
        Returns:
            - merged: List of complete tenant records with credentials
            - unmatched_tenants: Tenants without matching credentials
            - unmatched_creds: Credential domains without matching tenant
        """
        merged = []
        unmatched_tenants = []
        used_domains = set()
        
        for tenant in tenant_list:
            domain = tenant["onmicrosoft_domain"].lower()
            
            # Look up credentials by domain
            cred = credentials.get(domain)
            
            if cred:
                # Found matching credentials
                merged.append({
                    "name": tenant["company_name"],
                    "onmicrosoft_domain": tenant["onmicrosoft_domain"],
                    "microsoft_tenant_id": tenant["tenant_id"],
                    "address": tenant["address"],
                    "contact_name": tenant["contact_name"],
                    "contact_email": tenant["contact_email"],
                    "contact_phone": tenant["contact_phone"],
                    "admin_email": cred.email,  # Use email from credentials file
                    "admin_password": cred.password,
                })
                used_domains.add(domain)
            else:
                # No credentials found for this tenant
                unmatched_tenants.append(tenant)
                # Still add tenant but without password
                merged.append({
                    "name": tenant["company_name"],
                    "onmicrosoft_domain": tenant["onmicrosoft_domain"],
                    "microsoft_tenant_id": tenant["tenant_id"],
                    "address": tenant["address"],
                    "contact_name": tenant["contact_name"],
                    "contact_email": tenant["contact_email"],
                    "contact_phone": tenant["contact_phone"],
                    "admin_email": f"admin@{tenant['onmicrosoft_domain']}",
                    "admin_password": "",  # No password found
                })
        
        # Find credentials that weren't matched to any tenant
        unmatched_creds = [
            domain for domain in credentials.keys()
            if domain not in used_domains
        ]
        
        return merged, unmatched_tenants, unmatched_creds
    
    async def import_tenants(
        self,
        db: AsyncSession,
        batch_id: UUID,
        csv_content: str,
        credentials_content: str,
        provider: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Import tenants from both files.

        Matches by onmicrosoft domain, NOT by row position.

        Only imports as many tenants as there are domains needing tenants
        in the batch (domains without a linked tenant). Tenants already
        in the system are skipped and do not count toward this limit.
        """

        # Count how many domains in this batch still need a tenant
        domains_needing_tenants = (await db.execute(
            select(Domain).where(
                Domain.batch_id == batch_id,
                Domain.tenant_id == None
            )
        )).scalars().all()
        needed_count = len(domains_needing_tenants)

        tenant_list = self.parse_tenant_csv(csv_content)
        credentials = self.parse_credentials_txt(credentials_content)
        merged, unmatched_tenants, unmatched_creds = self.merge_data(tenant_list, credentials)

        imported = 0
        skipped = 0
        skipped_limit = 0
        missing_pwd = 0

        for data in merged:
            # Stop importing once we have enough tenants for the available domains
            if imported >= needed_count:
                skipped_limit += 1
                continue

            # Check duplicate by tenant ID or domain
            existing = None
            if data["microsoft_tenant_id"]:
                existing = await db.execute(
                    select(Tenant).where(
                        Tenant.microsoft_tenant_id == data["microsoft_tenant_id"]
                    )
                )
                existing = existing.scalar_one_or_none()

            if not existing:
                # Also check by domain
                existing = await db.execute(
                    select(Tenant).where(
                        Tenant.onmicrosoft_domain == data["onmicrosoft_domain"]
                    )
                )
                existing = existing.scalar_one_or_none()

            if existing:
                skipped += 1
                continue

            if not data["admin_password"]:
                missing_pwd += 1

            initial_pwd = data["admin_password"] or ""

            tenant = Tenant(
                batch_id=batch_id,
                name=data["name"],
                onmicrosoft_domain=data["onmicrosoft_domain"],
                microsoft_tenant_id=data["microsoft_tenant_id"],
                address=data["address"],
                contact_name=data["contact_name"],
                contact_email=data["contact_email"],
                contact_phone=data["contact_phone"],
                admin_email=data["admin_email"],
                admin_password=initial_pwd,       # Current password (will be updated after change)
                initial_password=initial_pwd,     # Original password (never changes)
                provider=provider or "Unknown",   # Required field - default if not provided
                status=TenantStatus.IMPORTED
            )
            db.add(tenant)
            imported += 1

        await db.commit()

        return {
            "total_csv": len(tenant_list),
            "total_credentials": len(credentials),
            "imported": imported,
            "skipped_duplicate": skipped,
            "skipped_not_needed": skipped_limit,
            "domains_needing_tenants": needed_count,
            "missing_password": missing_pwd,
            "unmatched_tenants": len(unmatched_tenants),
            "unmatched_credentials": len(unmatched_creds),
            "warnings": {
                "tenants_without_creds": [t["onmicrosoft_domain"] for t in unmatched_tenants],
                "creds_without_tenant": unmatched_creds
            }
        }
    
    async def auto_link_domains(
        self,
        db: AsyncSession,
        batch_id: UUID
    ) -> Dict[str, Any]:
        """Auto-link tenants to domains (1:1 in order)."""
        
        # Get unlinked tenants
        tenants = (await db.execute(
            select(Tenant).where(
                Tenant.batch_id == batch_id,
                Tenant.domain_id == None
            ).order_by(Tenant.created_at)
        )).scalars().all()
        
        # Get unlinked domains
        domains = (await db.execute(
            select(Domain).where(
                Domain.batch_id == batch_id
            ).order_by(Domain.created_at)
        )).scalars().all()
        
        # Filter domains not already linked
        available_domains = [d for d in domains if not any(t.domain_id == d.id for t in tenants)]
        
        linked = 0
        for tenant, domain in zip(tenants, available_domains):
            tenant.domain_id = domain.id
            tenant.custom_domain = domain.name
            linked += 1
        
        await db.commit()
        
        return {
            "tenants_available": len(tenants),
            "domains_available": len(available_domains),
            "linked": linked
        }


tenant_import_service = TenantImportService()