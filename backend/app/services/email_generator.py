"""
Email Generator Service

Generates 50 unique email addresses from a display name using proven patterns.
NO numbers, NO random suffixes - strictly name-based patterns only.
"""

import secrets
import string
from typing import List, Dict


# The 50 email patterns in EXACT order
EMAIL_PATTERNS = [
    "{first}",
    "{f}",
    "{first}.{last}",
    "{f}{last}",
    "{f}.{last}",
    "{last}.{first}",
    "{last}{f}",
    "{first}{last}",
    "{last}{first}",
    "{f}{l}",
    "{first}_{last}",
    "{last}_{first}",
    "{first}-{last}",
    "{last}-{first}",
    "{last}.{f}",
    "{f2}{last}",
    "{f2}.{last}",
    "{last}{f2}",
    "{last}.{f2}",
    "{f3}{last}",
    "{f3}.{last}",
    "{last}{f3}",
    "{last}.{f3}",
    "{first}{l}",
    "{first}.{l}",
    "{l}{first}",
    "{l}.{first}",
    "{first}{l2}",
    "{first}.{l2}",
    "{l2}{first}",
    "{l2}.{first}",
    "{first}{l3}",
    "{first}.{l3}",
    "{l3}{first}",
    "{l3}.{first}",
    "{first}{l4}",
    "{first}.{l4}",
    "{l4}{first}",
    "{l4}.{first}",
    "{first}{l5}",
    "{first}.{l5}",
    "{l5}{first}",
    "{l5}.{first}",
    "{first}{l6}",
    "{first}.{l6}",
    "{l6}{first}",
    "{l6}.{first}",
    "{f}.{l}",
    "{f}{l2}",
    "{f}.{l2}",
]


def generate_password(length: int = 12) -> str:
    """
    Generate a secure password.
    
    Requirements:
    - At least one lowercase letter
    - At least one uppercase letter
    - At least one digit
    - At least one special character
    - No ambiguous characters (0, O, l, 1, I)
    - Compliant with M365 password policy
    """
    # Character sets (excluding ambiguous characters)
    lowercase = "abcdefghjkmnpqrstuvwxyz"  # no l
    uppercase = "ABCDEFGHJKMNPQRSTUVWXYZ"  # no I, O
    digits = "23456789"  # no 0, 1
    special = "!@#$%^&*()-_=+"
    
    # Ensure at least one of each required type
    password = [
        secrets.choice(lowercase),
        secrets.choice(uppercase),
        secrets.choice(digits),
        secrets.choice(special),
    ]
    
    # Fill remaining length with random mix
    all_chars = lowercase + uppercase + digits + special
    password.extend(secrets.choice(all_chars) for _ in range(length - 4))
    
    # Shuffle to randomize position of required characters
    password_list = list(password)
    secrets.SystemRandom().shuffle(password_list)
    
    return ''.join(password_list)


def parse_display_name(display_name: str) -> tuple:
    """
    Parse display name into first and last name.
    
    Args:
        display_name: Full name like "Jack Zuvelek"
    
    Returns:
        Tuple of (first_name, last_name) in lowercase
    """
    parts = display_name.strip().split()
    
    if len(parts) < 2:
        raise ValueError(f"Display name must have first and last name: '{display_name}'")
    
    first = parts[0].lower()
    last = parts[-1].lower()  # Use last part as surname (handles middle names)
    
    return first, last


def generate_local_part(pattern: str, first: str, last: str) -> str:
    """
    Generate the local part of an email (before @) from a pattern.
    
    Args:
        pattern: Email pattern like "{first}.{last}"
        first: First name in lowercase
        last: Last name in lowercase
    
    Returns:
        Local part of email address
    """
    # Create all the substitution values
    substitutions = {
        "first": first,
        "last": last,
        "f": first[0] if len(first) >= 1 else "",
        "l": last[0] if len(last) >= 1 else "",
        "f2": first[:2] if len(first) >= 2 else first,
        "f3": first[:3] if len(first) >= 3 else first,
        "l2": last[:2] if len(last) >= 2 else last,
        "l3": last[:3] if len(last) >= 3 else last,
        "l4": last[:4] if len(last) >= 4 else last,
        "l5": last[:5] if len(last) >= 5 else last,
        "l6": last[:6] if len(last) >= 6 else last,
    }
    
    # Replace all placeholders
    result = pattern
    for key, value in substitutions.items():
        result = result.replace("{" + key + "}", value)
    
    return result


def generate_emails_for_domain(
    display_name: str,
    domain: str,
    count: int = 50
) -> List[Dict[str, str]]:
    """
    Generate email addresses for a domain.
    
    Args:
        display_name: Full name like "Jack Zuvelek"
        domain: Domain like "loancatermail13.info"
        count: Number of emails to generate (default 50)
    
    Returns:
        List of dicts with keys: email, display_name, password, local_part
    """
    first, last = parse_display_name(display_name)
    
    emails = []
    used_local_parts = set()
    
    # Use patterns up to count
    patterns_to_use = EMAIL_PATTERNS[:count]
    
    for pattern in patterns_to_use:
        local_part = generate_local_part(pattern, first, last)
        
        # Skip if we somehow get a duplicate (shouldn't happen with these patterns)
        if local_part in used_local_parts:
            continue
        
        used_local_parts.add(local_part)
        
        email = f"{local_part}@{domain}"
        password = generate_password()
        
        # Ensure password doesn't contain parts of email
        while (local_part in password.lower() or 
               first in password.lower() or 
               last in password.lower()):
            password = generate_password()
        
        emails.append({
            "email": email,
            "display_name": display_name,  # Keep original casing
            "password": password,
            "local_part": local_part
        })
    
    return emails


def generate_email_addresses(
    first_name: str,
    last_name: str,
    domain: str,
    count: int = 50
) -> List[Dict[str, str]]:
    """
    Backward compatibility wrapper for orchestrator.py.
    
    Args:
        first_name: First name like "Jack"
        last_name: Last name like "Zuvelek"
        domain: Domain like "loancatermail13.info"
        count: Number of emails to generate (default 50)
    
    Returns:
        List of dicts with keys: email, display_name, password
    """
    display_name = f"{first_name} {last_name}"
    return generate_emails_for_domain(display_name, domain, count)


def generate_emails_for_batch(
    display_name: str,
    domains: List[str],
    emails_per_domain: int = 50
) -> List[Dict[str, str]]:
    """
    Generate emails for multiple domains in a batch.
    
    Args:
        display_name: Full name like "Jack Zuvelek"
        domains: List of domains
        emails_per_domain: Number of emails per domain (default 50)
    
    Returns:
        List of all email dicts across all domains
    """
    all_emails = []
    
    for domain in domains:
        domain_emails = generate_emails_for_domain(
            display_name=display_name,
            domain=domain,
            count=emails_per_domain
        )
        all_emails.extend(domain_emails)
    
    return all_emails


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    # Test with sample data
    test_display_name = "Jack Zuvelek"
    test_domain = "loancatermail13.info"
    
    print(f"Generating emails for '{test_display_name}' @ {test_domain}")
    print("=" * 60)
    
    emails = generate_emails_for_domain(test_display_name, test_domain)
    
    for i, email_data in enumerate(emails, 1):
        print(f"{i:2}. {email_data['email']:40} | {email_data['password']}")
    
    print("=" * 60)
    print(f"Total: {len(emails)} emails generated")
    
    # Verify all emails are unique
    email_set = set(e['email'] for e in emails)
    print(f"Unique: {len(email_set)} (should match total)")
    
    # Verify no numbers in local parts
    has_numbers = any(any(c.isdigit() for c in e['local_part']) for e in emails)
    print(f"Contains numbers: {has_numbers} (should be False)")
