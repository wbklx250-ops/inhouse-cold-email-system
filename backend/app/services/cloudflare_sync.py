import httpx
import os
import logging

logger = logging.getLogger(__name__)
CF_API = "https://api.cloudflare.com/client/v4"

def _get_creds():
    """Get Cloudflare credentials."""
    email = os.environ.get("CLOUDFLARE_EMAIL")
    key = os.environ.get("CLOUDFLARE_API_KEY")
    
    if not email or not key:
        for env_path in [".env", "../.env", "backend/.env"]:
            try:
                with open(env_path) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("CLOUDFLARE_EMAIL="):
                            email = line.split("=", 1)[1].strip().strip('"').strip("'")
                        elif line.startswith("CLOUDFLARE_API_KEY="):
                            key = line.split("=", 1)[1].strip().strip('"').strip("'")
                if email and key:
                    break
            except:
                continue
    
    if not email or not key:
        raise ValueError("Cloudflare credentials missing!")
    
    return email, key

def _headers():
    email, key = _get_creds()
    return {"X-Auth-Email": email, "X-Auth-Key": key, "Content-Type": "application/json"}


def _cf_success(resp) -> bool:
    """
    Check if a Cloudflare API response was truly successful.
    
    Cloudflare API v4 can return HTTP 200 with {"success": false} in the body.
    We must check BOTH the HTTP status code AND the JSON body's success field.
    
    Args:
        resp: httpx.Response object
        
    Returns:
        True only if HTTP status is 200 AND body has "success": true
    """
    if resp.status_code != 200:
        return False
    try:
        data = resp.json()
        return data.get("success", False) is True
    except Exception:
        return False


def _cf_error_message(resp) -> str:
    """
    Extract a human-readable error message from a Cloudflare API response.
    
    Args:
        resp: httpx.Response object
        
    Returns:
        Error message string
    """
    try:
        data = resp.json()
        errors = data.get("errors", [])
        if errors:
            # Cloudflare errors have "code" and "message" fields
            messages = [f"{e.get('code', '?')}: {e.get('message', 'Unknown')}" for e in errors]
            return "; ".join(messages)
        if not data.get("success", True):
            return f"API returned success=false (HTTP {resp.status_code})"
    except Exception:
        pass
    return f"HTTP {resp.status_code}: {resp.text[:200]}"


def delete_records_by_type(zone_id, record_type, name_contains=None):
    """Delete ALL records of a specific type, optionally filtering by name."""
    logger.info(f"Deleting {record_type} records{' containing ' + name_contains if name_contains else ''}...")
    try:
        headers = _headers()
        resp = httpx.get(f"{CF_API}/zones/{zone_id}/dns_records?type={record_type}", headers=headers, timeout=30)
        if _cf_success(resp):
            records = resp.json().get("result", [])
            for r in records:
                should_delete = True
                if name_contains and name_contains not in r.get("name", ""):
                    should_delete = False
                
                if should_delete:
                    del_resp = httpx.delete(f"{CF_API}/zones/{zone_id}/dns_records/{r['id']}", headers=headers, timeout=30)
                    if _cf_success(del_resp):
                        logger.info(f"Deleted {record_type}: {r.get('name')} -> {r.get('content', '')[:50]}")
                    else:
                        logger.warning(f"Failed to delete {r['id']}: {_cf_error_message(del_resp)}")
        elif resp.status_code == 200:
            logger.warning(f"Cloudflare returned 200 but success=false listing {record_type} records: {_cf_error_message(resp)}")
        return True
    except Exception as e:
        logger.error(f"Error deleting {record_type} records: {e}")
        return False

def cleanup_before_verification(zone_id):
    """
    Clean up DNS records that would interfere with M365 domain verification.
    
    M365 verification checks TXT records at @ and flags ANY unexpected TXT records
    as "Invalid entry", causing verification to fail. This function removes:
    - ALL old MS=ms* verification codes (from previous attempts)
    - SPF records (v=spf1...) left over from previous failed Step 5 runs
    
    Does NOT touch: proxied CNAMEs (redirects), DMARC, A/AAAA records, etc.
    """
    logger.info(f"=== CLEANUP BEFORE VERIFICATION ===")
    try:
        headers = _headers()
        resp = httpx.get(f"{CF_API}/zones/{zone_id}/dns_records?type=TXT", headers=headers, timeout=30)
        if _cf_success(resp):
            for r in resp.json().get("result", []):
                content = r.get("content", "")
                record_name = r.get("name", "")
                
                # Delete ALL MS= verification records (old codes from previous attempts)
                if content.startswith("MS=") or content.startswith("ms="):
                    del_resp = httpx.delete(f"{CF_API}/zones/{zone_id}/dns_records/{r['id']}", headers=headers, timeout=30)
                    if _cf_success(del_resp):
                        logger.info(f"Deleted old verification TXT: {content}")
                    else:
                        logger.warning(f"Failed to delete old verification TXT {content}: {_cf_error_message(del_resp)}")
                
                # Delete SPF records at root (leftover from previous failed runs)
                # These cause M365 to flag as "Invalid entry" during verification
                elif "v=spf1" in content.lower():
                    del_resp = httpx.delete(f"{CF_API}/zones/{zone_id}/dns_records/{r['id']}", headers=headers, timeout=30)
                    if _cf_success(del_resp):
                        logger.info(f"Deleted leftover SPF TXT: {content[:60]}")
                    else:
                        logger.warning(f"Failed to delete leftover SPF TXT: {_cf_error_message(del_resp)}")
        elif resp.status_code == 200:
            logger.warning(f"Cloudflare returned 200 but success=false listing TXT records: {_cf_error_message(resp)}")
        else:
            logger.error(f"Failed to list TXT records for cleanup: {_cf_error_message(resp)}")
        
        logger.info(f"=== CLEANUP BEFORE VERIFICATION COMPLETE ===")
        return True
    except Exception as e:
        logger.error(f"Cleanup before verification error: {e}")
        return False


def cleanup_before_dns_setup(zone_id):
    """
    Clean up DNS records that would conflict with M365 email DNS setup.
    
    Removes records that conflict with what Step 5 is about to add:
    - Old MX records (will be replaced with M365 MX)
    - Old SPF TXT records (will be replaced with M365 SPF)
    - Old autodiscover CNAMEs (will be replaced)
    - Old DKIM selector CNAMEs (will be replaced)
    - A/AAAA records for 'autodiscover' subdomain (conflict with CNAME)
    - A/AAAA records for selector1/selector2._domainkey (conflict with CNAME)
    
    Does NOT touch: proxied CNAME at @ (redirect), DMARC records, other TXT records
    """
    logger.info(f"=== CLEANUP BEFORE DNS SETUP ===")
    try:
        headers = _headers()
        
        # Get ALL DNS records for the zone
        resp = httpx.get(f"{CF_API}/zones/{zone_id}/dns_records", headers=headers, timeout=30)
        if not _cf_success(resp):
            logger.error(f"Failed to list DNS records: {_cf_error_message(resp)}")
            return False
        
        records = resp.json().get("result", [])
        
        for r in records:
            record_type = r.get("type", "")
            record_name = r.get("name", "")
            content = r.get("content", "")
            proxied = r.get("proxied", False)
            
            should_delete = False
            reason = ""
            
            # Delete old MX records (will be replaced)
            if record_type == "MX":
                should_delete = True
                reason = "old MX record"
            
            # Delete old SPF TXT records (will be replaced)
            elif record_type == "TXT" and "v=spf1" in content.lower():
                should_delete = True
                reason = "old SPF TXT"
            
            # NOTE: Do NOT delete MS= verification records here!
            # They don't conflict with MX/SPF/CNAME setup and deleting them
            # breaks M365 verification if it hasn't completed yet.
            
            # Delete CNAME/A/AAAA for autodiscover (conflicts with new CNAME)
            elif "autodiscover" in record_name.lower() and record_type in ("CNAME", "A", "AAAA"):
                should_delete = True
                reason = f"old autodiscover {record_type}"
            
            # Delete CNAME/A/AAAA for DKIM selectors (conflicts with new CNAMEs)
            elif ("selector1._domainkey" in record_name.lower() or "selector2._domainkey" in record_name.lower()) and record_type in ("CNAME", "A", "AAAA"):
                should_delete = True
                reason = f"old DKIM {record_type}"
            
            if should_delete:
                del_resp = httpx.delete(f"{CF_API}/zones/{zone_id}/dns_records/{r['id']}", headers=headers, timeout=30)
                if _cf_success(del_resp):
                    logger.info(f"Deleted {reason}: {record_type} {record_name} -> {content[:60]}")
                else:
                    logger.warning(f"Failed to delete {reason} ({record_type} {record_name}): {_cf_error_message(del_resp)}")
        
        logger.info(f"=== CLEANUP BEFORE DNS SETUP COMPLETE ===")
        return True
    except Exception as e:
        logger.error(f"Cleanup before DNS setup error: {e}")
        return False


def _verify_record_exists(zone_id, record_type, content_search, headers):
    """
    Verify a DNS record actually exists in Cloudflare after creation.
    
    Args:
        zone_id: Cloudflare zone ID
        record_type: DNS record type (TXT, MX, CNAME)
        content_search: String to search for in record content
        headers: API headers
        
    Returns:
        True if record found, False otherwise
    """
    try:
        resp = httpx.get(f"{CF_API}/zones/{zone_id}/dns_records?type={record_type}", headers=headers, timeout=30)
        if _cf_success(resp):
            for r in resp.json().get("result", []):
                if content_search.lower() in r.get("content", "").lower():
                    return True
        return False
    except Exception as e:
        logger.warning(f"Verification check failed: {e}")
        return False


def add_txt(zone_id, value):
    """Add TXT record, deleting ALL existing MS= records first.
    
    IMPORTANT: Checks both HTTP status code AND Cloudflare API success field
    to ensure the record was actually created.
    """
    logger.info(f"Adding TXT: {value}")
    try:
        headers = _headers()
        
        # Delete ALL existing MS= verification records (may be multiple from retries)
        resp = httpx.get(f"{CF_API}/zones/{zone_id}/dns_records?type=TXT", headers=headers, timeout=30)
        if _cf_success(resp):
            for r in resp.json().get("result", []):
                content = r.get("content", "")
                if content.startswith("MS=") or content.startswith("ms="):
                    del_resp = httpx.delete(f"{CF_API}/zones/{zone_id}/dns_records/{r['id']}", headers=headers, timeout=30)
                    if _cf_success(del_resp):
                        logger.info(f"Deleted old TXT: {content}")
                    else:
                        logger.warning(f"Failed to delete old TXT {content}: {_cf_error_message(del_resp)}")
        elif resp.status_code == 200:
            logger.warning(f"Cloudflare returned 200 but success=false listing TXT records: {_cf_error_message(resp)}")
        
        # Add new
        resp = httpx.post(f"{CF_API}/zones/{zone_id}/dns_records", headers=headers,
                          json={"type": "TXT", "name": "@", "content": value, "ttl": 1}, timeout=30)
        
        if _cf_success(resp):
            record_id = resp.json().get("result", {}).get("id", "unknown")
            logger.info(f"TXT added successfully (record_id={record_id})")
            
            # Double-check: Verify the record actually exists
            if _verify_record_exists(zone_id, "TXT", value, headers):
                logger.info(f"TXT record verified in Cloudflare: {value}")
            else:
                logger.warning(f"TXT record NOT found in Cloudflare after creation! API said success but record missing.")
            
            return True
        elif "already exists" in resp.text.lower():
            logger.info("TXT already exists")
            return True
        else:
            error_msg = _cf_error_message(resp)
            logger.error(f"TXT add FAILED: {error_msg}")
            logger.error(f"TXT full response: status={resp.status_code}, body={resp.text[:500]}")
            return False
    except Exception as e:
        logger.error(f"TXT error: {e}")
        return False

def add_mx(zone_id, target, priority=0):
    """Add MX record, deleting ALL existing MX records first.
    
    IMPORTANT: Checks both HTTP status code AND Cloudflare API success field.
    """
    logger.info(f"Adding MX: {target} (priority {priority})")
    try:
        headers = _headers()
        
        # DELETE ALL existing MX records
        resp = httpx.get(f"{CF_API}/zones/{zone_id}/dns_records?type=MX", headers=headers, timeout=30)
        if _cf_success(resp):
            for r in resp.json().get("result", []):
                del_resp = httpx.delete(f"{CF_API}/zones/{zone_id}/dns_records/{r['id']}", headers=headers, timeout=30)
                if _cf_success(del_resp):
                    logger.info(f"Deleted existing MX: {r.get('content')}")
                else:
                    logger.warning(f"Failed to delete existing MX: {_cf_error_message(del_resp)}")
        
        # Add new
        resp = httpx.post(f"{CF_API}/zones/{zone_id}/dns_records", headers=headers,
                          json={"type": "MX", "name": "@", "content": target, "priority": priority, "ttl": 1}, timeout=30)
        
        if _cf_success(resp):
            record_id = resp.json().get("result", {}).get("id", "unknown")
            logger.info(f"MX added successfully (record_id={record_id})")
            return True
        else:
            error_msg = _cf_error_message(resp)
            logger.error(f"MX add FAILED: {error_msg}")
            logger.error(f"MX full response: status={resp.status_code}, body={resp.text[:500]}")
            return False
    except Exception as e:
        logger.error(f"MX error: {e}")
        return False

def add_spf(zone_id, value):
    """Add SPF record, deleting ALL existing SPF records first.
    
    IMPORTANT: Checks both HTTP status code AND Cloudflare API success field.
    """
    logger.info(f"Adding SPF: {value}")
    try:
        headers = _headers()
        
        # DELETE ALL existing SPF records (TXT records containing v=spf1)
        resp = httpx.get(f"{CF_API}/zones/{zone_id}/dns_records?type=TXT", headers=headers, timeout=30)
        if _cf_success(resp):
            for r in resp.json().get("result", []):
                if "v=spf1" in r.get("content", ""):
                    del_resp = httpx.delete(f"{CF_API}/zones/{zone_id}/dns_records/{r['id']}", headers=headers, timeout=30)
                    if _cf_success(del_resp):
                        logger.info(f"Deleted existing SPF: {r.get('content')[:50]}")
                    else:
                        logger.warning(f"Failed to delete existing SPF: {_cf_error_message(del_resp)}")
        
        # Add new
        resp = httpx.post(f"{CF_API}/zones/{zone_id}/dns_records", headers=headers,
                          json={"type": "TXT", "name": "@", "content": value, "ttl": 1}, timeout=30)
        
        if _cf_success(resp):
            record_id = resp.json().get("result", {}).get("id", "unknown")
            logger.info(f"SPF added successfully (record_id={record_id})")
            return True
        else:
            error_msg = _cf_error_message(resp)
            logger.error(f"SPF add FAILED: {error_msg}")
            logger.error(f"SPF full response: status={resp.status_code}, body={resp.text[:500]}")
            return False
    except Exception as e:
        logger.error(f"SPF error: {e}")
        return False

def add_cname(zone_id, name, target):
    """Add CNAME record, deleting existing record with same name first.
    
    IMPORTANT: Checks both HTTP status code AND Cloudflare API success field.
    """
    logger.info(f"Adding CNAME: {name} -> {target}")
    try:
        headers = _headers()
        
        # Get zone details to get the domain name
        zone_resp = httpx.get(f"{CF_API}/zones/{zone_id}", headers=headers, timeout=30)
        domain = ""
        if _cf_success(zone_resp):
            domain = zone_resp.json().get("result", {}).get("name", "")
        
        # Build full record name
        if domain and not name.endswith(domain):
            full_name = f"{name}.{domain}"
        else:
            full_name = name
        
        # DELETE existing CNAME with this name
        resp = httpx.get(f"{CF_API}/zones/{zone_id}/dns_records?type=CNAME", headers=headers, timeout=30)
        if _cf_success(resp):
            for r in resp.json().get("result", []):
                if name in r.get("name", "") or r.get("name", "") == full_name:
                    del_resp = httpx.delete(f"{CF_API}/zones/{zone_id}/dns_records/{r['id']}", headers=headers, timeout=30)
                    if _cf_success(del_resp):
                        logger.info(f"Deleted existing CNAME: {r.get('name')}")
                    else:
                        logger.warning(f"Failed to delete existing CNAME {r.get('name')}: {_cf_error_message(del_resp)}")
        
        # Add new
        resp = httpx.post(f"{CF_API}/zones/{zone_id}/dns_records", headers=headers,
                          json={"type": "CNAME", "name": name, "content": target, "ttl": 1, "proxied": False}, timeout=30)
        
        if _cf_success(resp):
            record_id = resp.json().get("result", {}).get("id", "unknown")
            logger.info(f"CNAME added successfully: {name} -> {target} (record_id={record_id})")
            return True
        elif "already exists" in resp.text.lower():
            logger.info("CNAME already exists")
            return True
        else:
            error_msg = _cf_error_message(resp)
            logger.error(f"CNAME add FAILED ({name} -> {target}): {error_msg}")
            logger.error(f"CNAME full response: status={resp.status_code}, body={resp.text[:500]}")
            return False
    except Exception as e:
        logger.error(f"CNAME error: {e}")
        return False

def add_dkim(zone_id, selector1_target, selector2_target):
    """Add both DKIM CNAME records, deleting existing first."""
    logger.info(f"Adding DKIM records")
    
    # Delete existing DKIM records
    try:
        headers = _headers()
        resp = httpx.get(f"{CF_API}/zones/{zone_id}/dns_records?type=CNAME", headers=headers, timeout=30)
        if _cf_success(resp):
            for r in resp.json().get("result", []):
                if "selector1" in r.get("name", "") or "selector2" in r.get("name", ""):
                    del_resp = httpx.delete(f"{CF_API}/zones/{zone_id}/dns_records/{r['id']}", headers=headers, timeout=30)
                    if _cf_success(del_resp):
                        logger.info(f"Deleted existing DKIM: {r.get('name')}")
                    else:
                        logger.warning(f"Failed to delete existing DKIM {r.get('name')}: {_cf_error_message(del_resp)}")
    except Exception as e:
        logger.warning(f"Error cleaning up old DKIM records: {e}")
    
    # Add selector1
    result1 = add_cname(zone_id, "selector1._domainkey", selector1_target)
    
    # Add selector2
    result2 = add_cname(zone_id, "selector2._domainkey", selector2_target)
    
    return result1 and result2
