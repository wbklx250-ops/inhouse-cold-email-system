"""
Email Address Generator

Generates 50 professional email variations from a persona name.
Uses ONLY combinations of first name and last name with separators (. _ -)
NO numbers, NO prefixes like "mail.", NO suffixes like ".work"
"""

import secrets
import string
from typing import List, Dict


def generate_password(length: int = 16) -> str:
    """Generate a secure random password."""
    chars = string.ascii_letters + string.digits + "!@#$%"
    password = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%"),
    ]
    password.extend(secrets.choice(chars) for _ in range(length - 4))
    password_list = list(password)
    secrets.SystemRandom().shuffle(password_list)
    return ''.join(password_list)


def generate_email_addresses(
    first_name: str,
    last_name: str,
    domain: str,
    count: int = 50
) -> List[Dict[str, str]]:
    """
    Generate unique email addresses for a domain.
    
    Uses ONLY variations of first/last name:
    - Full names: pierre, mechen, pierremechen
    - Initials: p, pm
    - Truncations: pi, pie, pier, pierr
    - Separators: . _ -
    
    Returns list of:
    {
        "email": "john.smith@domain.com",
        "display_name": "John Smith",
        "password": "SecurePass123!"
    }
    """
    first = first_name.lower().strip()
    last = last_name.lower().strip()
    
    # Generate truncations of first name (1 to len-1 chars)
    first_truncations = [first[:i] for i in range(1, len(first))]
    
    # Generate truncations of last name (1 to len-1 chars)  
    last_truncations = [last[:i] for i in range(1, len(last))]
    
    emails_set = set()
    
    # === CORE PATTERNS (no separator) ===
    core_patterns = [
        first,                    # pierre
        first[0],                 # p
        f"{first}{last}",         # pierremechen
        f"{last}{first}",         # mechenpierre
        f"{first[0]}{last}",      # pmechen
        f"{last}{first[0]}",      # mechenp
        f"{first[0]}{last[0]}",   # pm
    ]
    emails_set.update(core_patterns)
    
    # === DOT SEPARATOR PATTERNS ===
    dot_patterns = [
        f"{first}.{last}",        # pierre.mechen
        f"{last}.{first}",        # mechen.pierre
        f"{first[0]}.{last}",     # p.mechen
        f"{last}.{first[0]}",     # mechen.p
    ]
    emails_set.update(dot_patterns)
    
    # === UNDERSCORE SEPARATOR PATTERNS ===
    underscore_patterns = [
        f"{first}_{last}",        # pierre_mechen
        f"{last}_{first}",        # mechen_pierre
    ]
    emails_set.update(underscore_patterns)
    
    # === HYPHEN SEPARATOR PATTERNS ===
    hyphen_patterns = [
        f"{first}-{last}",        # pierre-mechen
        f"{last}-{first}",        # mechen-pierre
    ]
    emails_set.update(hyphen_patterns)
    
    # === TRUNCATED FIRST NAME PATTERNS ===
    for trunc in first_truncations:
        if len(trunc) >= 2:  # Skip single char (already covered by initial)
            # No separator
            emails_set.add(f"{trunc}{last}")       # pi+mechen = pimechen
            emails_set.add(f"{last}{trunc}")       # mechen+pi = mechenpi
            # Dot separator
            emails_set.add(f"{trunc}.{last}")      # pi.mechen
            emails_set.add(f"{last}.{trunc}")      # mechen.pi
    
    # === TRUNCATED LAST NAME PATTERNS ===
    for trunc in last_truncations:
        # No separator
        emails_set.add(f"{first}{trunc}")          # pierre+m = pierrem
        emails_set.add(f"{trunc}{first}")          # m+pierre = mpierre
        # Dot separator
        emails_set.add(f"{first}.{trunc}")         # pierre.m
        emails_set.add(f"{trunc}.{first}")         # m.pierre
    
    # Convert to list and create output
    display_name = f"{first_name.title()} {last_name.title()}"
    
    emails = []
    for local in emails_set:
        if local and len(local) >= 1:  # Valid local part
            email = f"{local}@{domain}"
            emails.append({
                "email": email,
                "display_name": display_name,
                "password": generate_password()
            })
    
    # Sort by length (shorter emails first) for consistency
    emails.sort(key=lambda x: len(x["email"]))
    
    return emails[:count]


class EmailGenerator:
    """Email generator class for generating mailbox credentials."""
    
    def generate(
        self,
        first_name: str,
        last_name: str,
        domain: str,
        count: int = 50
    ) -> List[Dict[str, str]]:
        """Generate email addresses for a domain."""
        return generate_email_addresses(first_name, last_name, domain, count)


# Singleton instance
email_generator = EmailGenerator()


# Test the function
if __name__ == "__main__":
    emails = generate_email_addresses("Pierre", "Mechen", "vesselbridge-partners.com", 50)
    print(f"Generated {len(emails)} emails:\n")
    for e in emails:
        print(e["email"])