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

def delete_records_by_type(zone_id, record_type, name_contains=None):
    """Delete ALL records of a specific type, optionally filtering by name."""
    logger.info(f"Deleting {record_type} records{' containing ' + name_contains if name_contains else ''}...")
    try:
        headers = _headers()
        resp = httpx.get(f"{CF_API}/zones/{zone_id}/dns_records?type={record_type}", headers=headers, timeout=30)
        if resp.status_code == 200:
            records = resp.json().get("result", [])
            for r in records:
                should_delete = True
                if name_contains and name_contains not in r.get("name", ""):
                    should_delete = False
                
                if should_delete:
                    del_resp = httpx.delete(f"{CF_API}/zones/{zone_id}/dns_records/{r['id']}", headers=headers, timeout=30)
                    if del_resp.status_code == 200:
                        logger.info(f"Deleted {record_type}: {r.get('name')} -> {r.get('content', '')[:50]}")
                    else:
                        logger.warning(f"Failed to delete {r['id']}: {del_resp.text[:100]}")
        return True
    except Exception as e:
        logger.error(f"Error deleting {record_type} records: {e}")
        return False

def add_txt(zone_id, value):
    """Add TXT record, deleting existing MS= records first."""
    logger.info(f"Adding TXT: {value}")
    try:
        headers = _headers()
        
        # Delete existing MS= verification records
        resp = httpx.get(f"{CF_API}/zones/{zone_id}/dns_records?type=TXT", headers=headers, timeout=30)
        if resp.status_code == 200:
            for r in resp.json().get("result", []):
                if r.get("content", "").startswith("MS="):
                    httpx.delete(f"{CF_API}/zones/{zone_id}/dns_records/{r['id']}", headers=headers, timeout=30)
                    logger.info(f"Deleted old TXT: {r.get('content')}")
        
        # Add new
        resp = httpx.post(f"{CF_API}/zones/{zone_id}/dns_records", headers=headers,
                          json={"type": "TXT", "name": "@", "content": value, "ttl": 1}, timeout=30)
        
        if resp.status_code == 200:
            logger.info("TXT added successfully")
            return True
        elif "already exists" in resp.text.lower():
            logger.info("TXT already exists")
            return True
        else:
            logger.error(f"TXT failed: {resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"TXT error: {e}")
        return False

def add_mx(zone_id, target, priority=0):
    """Add MX record, deleting ALL existing MX records first."""
    logger.info(f"Adding MX: {target} (priority {priority})")
    try:
        headers = _headers()
        
        # DELETE ALL existing MX records
        resp = httpx.get(f"{CF_API}/zones/{zone_id}/dns_records?type=MX", headers=headers, timeout=30)
        if resp.status_code == 200:
            for r in resp.json().get("result", []):
                del_resp = httpx.delete(f"{CF_API}/zones/{zone_id}/dns_records/{r['id']}", headers=headers, timeout=30)
                logger.info(f"Deleted existing MX: {r.get('content')}")
        
        # Add new
        resp = httpx.post(f"{CF_API}/zones/{zone_id}/dns_records", headers=headers,
                          json={"type": "MX", "name": "@", "content": target, "priority": priority, "ttl": 1}, timeout=30)
        
        if resp.status_code == 200:
            logger.info("MX added successfully")
            return True
        else:
            logger.error(f"MX failed: {resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"MX error: {e}")
        return False

def add_spf(zone_id, value):
    """Add SPF record, deleting ALL existing SPF records first."""
    logger.info(f"Adding SPF: {value}")
    try:
        headers = _headers()
        
        # DELETE ALL existing SPF records (TXT records containing v=spf1)
        resp = httpx.get(f"{CF_API}/zones/{zone_id}/dns_records?type=TXT", headers=headers, timeout=30)
        if resp.status_code == 200:
            for r in resp.json().get("result", []):
                if "v=spf1" in r.get("content", ""):
                    del_resp = httpx.delete(f"{CF_API}/zones/{zone_id}/dns_records/{r['id']}", headers=headers, timeout=30)
                    logger.info(f"Deleted existing SPF: {r.get('content')[:50]}")
        
        # Add new
        resp = httpx.post(f"{CF_API}/zones/{zone_id}/dns_records", headers=headers,
                          json={"type": "TXT", "name": "@", "content": value, "ttl": 1}, timeout=30)
        
        if resp.status_code == 200:
            logger.info("SPF added successfully")
            return True
        else:
            logger.error(f"SPF failed: {resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"SPF error: {e}")
        return False

def add_cname(zone_id, name, target):
    """Add CNAME record, deleting existing record with same name first."""
    logger.info(f"Adding CNAME: {name} -> {target}")
    try:
        headers = _headers()
        
        # Get zone details to get the domain name
        zone_resp = httpx.get(f"{CF_API}/zones/{zone_id}", headers=headers, timeout=30)
        domain = ""
        if zone_resp.status_code == 200:
            domain = zone_resp.json().get("result", {}).get("name", "")
        
        # Build full record name
        if domain and not name.endswith(domain):
            full_name = f"{name}.{domain}"
        else:
            full_name = name
        
        # DELETE existing CNAME with this name
        resp = httpx.get(f"{CF_API}/zones/{zone_id}/dns_records?type=CNAME", headers=headers, timeout=30)
        if resp.status_code == 200:
            for r in resp.json().get("result", []):
                if name in r.get("name", "") or r.get("name", "") == full_name:
                    del_resp = httpx.delete(f"{CF_API}/zones/{zone_id}/dns_records/{r['id']}", headers=headers, timeout=30)
                    logger.info(f"Deleted existing CNAME: {r.get('name')}")
        
        # Add new
        resp = httpx.post(f"{CF_API}/zones/{zone_id}/dns_records", headers=headers,
                          json={"type": "CNAME", "name": name, "content": target, "ttl": 1, "proxied": False}, timeout=30)
        
        if resp.status_code == 200:
            logger.info("CNAME added successfully")
            return True
        elif "already exists" in resp.text.lower():
            logger.info("CNAME already exists")
            return True
        else:
            logger.error(f"CNAME failed: {resp.text[:200]}")
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
        if resp.status_code == 200:
            for r in resp.json().get("result", []):
                if "selector1" in r.get("name", "") or "selector2" in r.get("name", ""):
                    httpx.delete(f"{CF_API}/zones/{zone_id}/dns_records/{r['id']}", headers=headers, timeout=30)
                    logger.info(f"Deleted existing DKIM: {r.get('name')}")
    except:
        pass
    
    # Add selector1
    result1 = add_cname(zone_id, "selector1._domainkey", selector1_target)
    
    # Add selector2
    result2 = add_cname(zone_id, "selector2._domainkey", selector2_target)
    
    return result1 and result2
