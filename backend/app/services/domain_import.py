"""
Domain Import Service

Reads domain list from CSV including per-domain redirect URLs.
"""

import csv
import io
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class DomainImportData:
    """Data structure for imported domain information."""
    name: str
    redirect_url: Optional[str] = None
    registrar: Optional[str] = None


def parse_domains_csv(content: str) -> List[DomainImportData]:
    """
    Parse domains CSV file.
    
    Expected columns:
    - domain (required): The domain name
    - redirect (optional): Where to redirect the root domain
    - registrar (optional): Where domain was purchased
    
    Column names are flexible (case-insensitive, partial match).
    
    Example CSV:
    ```
    domain,redirect,registrar
    coldreach.io,https://google.com,porkbun
    outbound-mail.co,https://example.com,porkbun
    salesflow.net,https://company-website.com,porkbun
    ```
    
    Args:
        content: Raw CSV file content as string
        
    Returns:
        List of DomainImportData objects
        
    Raises:
        ValueError: If CSV is empty or has no valid domain column
    """
    reader = csv.DictReader(io.StringIO(content))
    domains = []
    
    if not reader.fieldnames:
        raise ValueError("CSV file is empty or has no headers")
    
    # Find columns by flexible matching
    domain_col = None
    redirect_col = None
    registrar_col = None
    
    for col in reader.fieldnames:
        col_lower = col.lower().strip()
        
        # Domain column - check various naming conventions
        if col_lower in ('domain', 'domain_name', 'domainname', 'name'):
            domain_col = col
        # Redirect column
        elif col_lower in ('redirect', 'redirect_url', 'redirecturl', 'redirect_to', 'url'):
            redirect_col = col
        # Registrar column
        elif col_lower in ('registrar', 'provider', 'source'):
            registrar_col = col
    
    if not domain_col:
        # Try first column as domain if no match found
        domain_col = reader.fieldnames[0]
    
    for row in reader:
        domain_name = row.get(domain_col, '').strip().lower()
        
        if not domain_name:
            continue
        
        # Remove any protocol if accidentally included
        domain_name = domain_name.replace('https://', '').replace('http://', '').rstrip('/')
        
        # Parse redirect URL
        redirect_url = None
        if redirect_col:
            redirect_url = row.get(redirect_col, '').strip()
            if redirect_url:
                # Ensure redirect has protocol
                if not redirect_url.startswith('http'):
                    redirect_url = f"https://{redirect_url}"
            else:
                redirect_url = None  # Empty string becomes None
        
        # Parse registrar
        registrar = None
        if registrar_col:
            registrar = row.get(registrar_col, '').strip() or None
        
        domains.append(DomainImportData(
            name=domain_name,
            redirect_url=redirect_url,
            registrar=registrar
        ))
    
    return domains


def validate_domains(domains: List[DomainImportData]) -> dict:
    """
    Validate a list of parsed domains.
    
    Returns dict with:
    - valid: list of valid DomainImportData
    - invalid: list of dicts with domain name and error
    """
    import re
    
    # Simple domain validation regex
    domain_pattern = re.compile(
        r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
    )
    
    valid = []
    invalid = []
    
    for domain in domains:
        if not domain.name:
            invalid.append({"domain": "(empty)", "error": "Empty domain name"})
            continue
            
        if not domain_pattern.match(domain.name):
            invalid.append({"domain": domain.name, "error": "Invalid domain format"})
            continue
        
        # Validate redirect URL if present
        if domain.redirect_url:
            if not domain.redirect_url.startswith(('http://', 'https://')):
                invalid.append({
                    "domain": domain.name, 
                    "error": f"Invalid redirect URL: {domain.redirect_url}"
                })
                continue
        
        valid.append(domain)
    
    return {"valid": valid, "invalid": invalid}