"""
Validation service for the upfront collection form.
Parses all 3 files, cross-validates, and returns a complete preview.
"""
import csv
import io
import re
import logging
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)


def parse_domains_csv_content(content: str) -> Tuple[List[Dict], List[str]]:
    """
    Parse domains CSV. Expected columns: domain (required), redirect_url (optional).
    Returns (parsed_domains, errors).
    """
    errors = []
    domains = []

    try:
        reader = csv.DictReader(io.StringIO(content))
        columns = reader.fieldnames or []

        # Check for domain column (flexible naming)
        domain_col = None
        for col in columns:
            if col.strip().lower() in ("domain", "domain_name", "name"):
                domain_col = col
                break

        if not domain_col:
            errors.append(f"CSV must have a 'domain' column. Found: {', '.join(columns)}")
            return domains, errors

        # Check for redirect column
        redirect_col = None
        for col in columns:
            if col.strip().lower() in ("redirect_url", "redirect", "url"):
                redirect_col = col
                break

        for i, row in enumerate(reader, start=2):
            domain_name = row.get(domain_col, "").strip().lower()
            if not domain_name:
                continue

            # Basic domain format validation
            if not re.match(r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z]{2,})+$', domain_name):
                errors.append(f"Row {i}: Invalid domain format: {domain_name}")
                continue

            redirect_url = row.get(redirect_col, "").strip() if redirect_col else ""
            domains.append({
                "name": domain_name,
                "redirect_url": redirect_url,
            })

    except Exception as e:
        errors.append(f"Failed to parse domains CSV: {str(e)}")

    return domains, errors


def parse_tenants_csv_content(content: str) -> Tuple[List[Dict], List[str]]:
    """
    Parse tenant CSV from reseller.
    Flexible column detection — handles various reseller formats.
    Returns (parsed_tenants, errors).
    """
    errors = []
    tenants = []

    try:
        reader = csv.DictReader(io.StringIO(content))
        columns = [c.strip() for c in (reader.fieldnames or [])]
        columns_lower = [c.lower() for c in columns]

        # Find the onmicrosoft domain column
        onmicrosoft_col = None
        for i, col in enumerate(columns_lower):
            if "onmicrosoft" in col or "domain" in col:
                onmicrosoft_col = columns[i]
                break

        # Find tenant name column
        name_col = None
        for i, col in enumerate(columns_lower):
            if "company" in col or "name" in col or "tenant" in col:
                name_col = columns[i]
                break

        # Find tenant ID column
        id_col = None
        for i, col in enumerate(columns_lower):
            if "uuid" in col or "tenant_id" in col or "id" in col:
                id_col = columns[i]
                break

        if not onmicrosoft_col:
            errors.append(f"Tenant CSV must have a column containing 'onmicrosoft' or 'domain'. Found: {', '.join(columns)}")
            return tenants, errors

        for i, row in enumerate(reader, start=2):
            onmicrosoft = row.get(onmicrosoft_col, "").strip()
            if not onmicrosoft:
                continue

            # Normalize: add .onmicrosoft.com if just the prefix
            if not onmicrosoft.endswith(".onmicrosoft.com"):
                onmicrosoft = f"{onmicrosoft}.onmicrosoft.com"

            tenants.append({
                "name": row.get(name_col, "").strip() if name_col else onmicrosoft.split(".")[0],
                "onmicrosoft_domain": onmicrosoft,
                "microsoft_tenant_id": row.get(id_col, "").strip() if id_col else "",
            })

    except Exception as e:
        errors.append(f"Failed to parse tenant CSV: {str(e)}")

    return tenants, errors


def parse_credentials_txt_content(content: str) -> Tuple[Dict[str, Dict], List[str]]:
    """
    Parse credentials TXT from reseller.
    Format: Username: admin@xyz.onmicrosoft.com / Password: abc123
    Returns (credentials_by_domain, errors).
    """
    errors = []
    credentials = {}

    try:
        lines = content.strip().split("\n")
        current_email = None

        for i, line in enumerate(lines, start=1):
            line = line.strip()
            if not line:
                continue

            if line.lower().startswith("username:"):
                current_email = line.split(":", 1)[1].strip()
            elif line.lower().startswith("password:") and current_email:
                password = line.split(":", 1)[1].strip()
                # Extract domain key
                domain_key = current_email.split("@")[1].lower() if "@" in current_email else ""
                if domain_key:
                    credentials[domain_key] = {
                        "email": current_email,
                        "password": password,
                    }
                current_email = None

    except Exception as e:
        errors.append(f"Failed to parse credentials TXT: {str(e)}")

    return credentials, errors


def cross_validate(
    domains: List[Dict],
    tenants: List[Dict],
    credentials: Dict[str, Dict],
    first_name: str,
    last_name: str,
    mailboxes_per_tenant: int = 50,
) -> Dict[str, Any]:
    """
    Cross-validate all inputs and return a complete preview.
    """
    errors = []
    warnings = []

    # 1. Match credentials to tenants
    matched_count = 0
    unmatched_tenants = []
    for tenant in tenants:
        domain_key = tenant["onmicrosoft_domain"].lower()
        if domain_key in credentials:
            tenant["admin_email"] = credentials[domain_key]["email"]
            tenant["admin_password"] = credentials[domain_key]["password"]
            matched_count += 1
        else:
            unmatched_tenants.append(tenant["onmicrosoft_domain"])

    if unmatched_tenants:
        warnings.append(f"{len(unmatched_tenants)} tenant(s) have no matching credentials")

    # 2. Check domain-tenant count alignment
    if len(domains) < len(tenants):
        warnings.append(f"More tenants ({len(tenants)}) than domains ({len(domains)}) — {len(tenants) - len(domains)} tenants won't get a domain")
    elif len(domains) > len(tenants):
        warnings.append(f"More domains ({len(domains)}) than tenants ({len(tenants)}) — {len(domains) - len(tenants)} extra domains")

    # 3. Check name generates enough patterns
    if len(first_name) < 2 or len(last_name) < 2:
        errors.append("First and last name must each be at least 2 characters for email generation")

    # 4. Calculate expected mailboxes
    linked_count = min(len(domains), len(tenants))
    expected_mailboxes = linked_count * mailboxes_per_tenant

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "domains_count": len(domains),
            "tenants_count": len(tenants),
            "credentials_matched": matched_count,
            "credentials_unmatched": len(unmatched_tenants),
            "domains_linked": linked_count,
            "expected_mailboxes": expected_mailboxes,
        }
    }
