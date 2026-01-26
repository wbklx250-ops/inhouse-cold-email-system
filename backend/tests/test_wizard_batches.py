"""
End-to-end tests for the batch-aware wizard system.

Tests the complete batch lifecycle including:
- Creating batches
- Listing batches
- Getting batch status
- Pausing/resuming batches
- Importing domains to batches
- Batch independence
- Deleting batches
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_batch(client: AsyncClient):
    """Test creating a new batch."""
    response = await client.post(
        "/api/v1/wizard/batches",
        json={"name": "Test Batch", "description": "Test description"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Batch"
    assert data["description"] == "Test description"
    assert data["current_step"] == 1
    assert data["status"] == "active"
    assert data["domains_count"] == 0
    assert data["tenants_count"] == 0
    assert data["mailboxes_count"] == 0
    assert "id" in data


@pytest.mark.asyncio
async def test_create_batch_with_redirect_url(client: AsyncClient):
    """Test creating a batch with redirect URL."""
    response = await client.post(
        "/api/v1/wizard/batches",
        json={
            "name": "Redirect Batch",
            "redirect_url": "https://example.com/landing"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Redirect Batch"
    assert data["redirect_url"] == "https://example.com/landing"


@pytest.mark.asyncio
async def test_list_batches_empty(client: AsyncClient):
    """Test listing batches when empty."""
    response = await client.get("/api/v1/wizard/batches")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 0


@pytest.mark.asyncio
async def test_list_batches(client: AsyncClient):
    """Test listing batches."""
    # Create a couple of batches first
    await client.post("/api/v1/wizard/batches", json={"name": "Batch 1"})
    await client.post("/api/v1/wizard/batches", json={"name": "Batch 2"})
    
    response = await client.get("/api/v1/wizard/batches")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2
    
    # Batches should be in reverse chronological order (newest first)
    names = [b["name"] for b in data]
    assert "Batch 1" in names
    assert "Batch 2" in names


@pytest.mark.asyncio
async def test_get_batch(client: AsyncClient):
    """Test getting a specific batch."""
    # Create batch
    create_resp = await client.post(
        "/api/v1/wizard/batches",
        json={"name": "Get Test", "description": "For testing get"}
    )
    batch_id = create_resp.json()["id"]
    
    # Get batch
    response = await client.get(f"/api/v1/wizard/batches/{batch_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == batch_id
    assert data["name"] == "Get Test"
    assert data["description"] == "For testing get"


@pytest.mark.asyncio
async def test_get_batch_not_found(client: AsyncClient):
    """Test getting a non-existent batch."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(f"/api/v1/wizard/batches/{fake_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_batch_status(client: AsyncClient):
    """Test getting batch status."""
    # Create batch
    create_resp = await client.post(
        "/api/v1/wizard/batches",
        json={"name": "Status Test"}
    )
    batch_id = create_resp.json()["id"]
    
    # Get status
    response = await client.get(f"/api/v1/wizard/batches/{batch_id}/status")
    assert response.status_code == 200
    data = response.json()
    assert data["batch_id"] == batch_id
    assert data["batch_name"] == "Status Test"
    assert data["current_step"] == 1
    assert data["step_name"] == "Import Domains"
    assert data["status"] == "active"
    assert data["domains_total"] == 0
    assert data["zones_created"] == 0
    assert data["tenants_total"] == 0
    assert data["mailboxes_total"] == 0


@pytest.mark.asyncio
async def test_batch_status_not_found(client: AsyncClient):
    """Test getting status of a non-existent batch."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(f"/api/v1/wizard/batches/{fake_id}/status")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_pause_batch(client: AsyncClient):
    """Test pausing a batch."""
    # Create batch
    create_resp = await client.post(
        "/api/v1/wizard/batches",
        json={"name": "Pause Test"}
    )
    batch_id = create_resp.json()["id"]
    
    # Pause
    pause_resp = await client.patch(f"/api/v1/wizard/batches/{batch_id}/pause")
    assert pause_resp.status_code == 200
    assert pause_resp.json()["success"] is True
    
    # Verify status changed
    status_resp = await client.get(f"/api/v1/wizard/batches/{batch_id}/status")
    assert status_resp.json()["status"] == "paused"


@pytest.mark.asyncio
async def test_resume_batch(client: AsyncClient):
    """Test resuming a paused batch."""
    # Create batch
    create_resp = await client.post(
        "/api/v1/wizard/batches",
        json={"name": "Resume Test"}
    )
    batch_id = create_resp.json()["id"]
    
    # Pause first
    await client.patch(f"/api/v1/wizard/batches/{batch_id}/pause")
    
    # Resume
    resume_resp = await client.patch(f"/api/v1/wizard/batches/{batch_id}/resume")
    assert resume_resp.status_code == 200
    assert resume_resp.json()["success"] is True
    
    # Verify status changed back
    status_resp = await client.get(f"/api/v1/wizard/batches/{batch_id}/status")
    assert status_resp.json()["status"] == "active"


@pytest.mark.asyncio
async def test_pause_resume_cycle(client: AsyncClient):
    """Test pausing and resuming a batch multiple times."""
    # Create batch
    create_resp = await client.post(
        "/api/v1/wizard/batches",
        json={"name": "Cycle Test"}
    )
    batch_id = create_resp.json()["id"]
    
    # Initial state should be active
    status1 = await client.get(f"/api/v1/wizard/batches/{batch_id}/status")
    assert status1.json()["status"] == "active"
    
    # Pause
    await client.patch(f"/api/v1/wizard/batches/{batch_id}/pause")
    status2 = await client.get(f"/api/v1/wizard/batches/{batch_id}/status")
    assert status2.json()["status"] == "paused"
    
    # Resume
    await client.patch(f"/api/v1/wizard/batches/{batch_id}/resume")
    status3 = await client.get(f"/api/v1/wizard/batches/{batch_id}/status")
    assert status3.json()["status"] == "active"
    
    # Pause again
    await client.patch(f"/api/v1/wizard/batches/{batch_id}/pause")
    status4 = await client.get(f"/api/v1/wizard/batches/{batch_id}/status")
    assert status4.json()["status"] == "paused"


@pytest.mark.asyncio
async def test_import_domains_to_batch(client: AsyncClient):
    """Test importing domains to a specific batch."""
    # Create batch
    create_resp = await client.post(
        "/api/v1/wizard/batches",
        json={"name": "Domain Import Test", "redirect_url": "https://example.com"}
    )
    batch_id = create_resp.json()["id"]
    
    # Create CSV content
    csv_content = "domain_name,registrar,registration_date\ntest1.com,Porkbun,2025-01-15\ntest2.com,Porkbun,2025-01-15"
    
    # Import domains
    response = await client.post(
        f"/api/v1/wizard/batches/{batch_id}/step1/import-domains",
        files={"file": ("domains.csv", csv_content.encode(), "text/csv")},
        data={"redirect_url": "https://example.com"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["details"]["created"] == 2
    assert data["details"]["skipped"] == 0
    
    # Verify batch status updated
    status_resp = await client.get(f"/api/v1/wizard/batches/{batch_id}/status")
    status_data = status_resp.json()
    assert status_data["domains_total"] == 2
    assert status_data["current_step"] == 2  # Should advance to step 2


@pytest.mark.asyncio
async def test_import_domains_with_duplicates(client: AsyncClient):
    """Test importing domains with duplicates is handled correctly."""
    # Create batch
    create_resp = await client.post(
        "/api/v1/wizard/batches",
        json={"name": "Duplicate Test"}
    )
    batch_id = create_resp.json()["id"]
    
    # First import
    csv1 = "domain_name\nexample1.com\nexample2.com"
    await client.post(
        f"/api/v1/wizard/batches/{batch_id}/step1/import-domains",
        files={"file": ("domains.csv", csv1.encode(), "text/csv")},
        data={"redirect_url": "https://test.com"}
    )
    
    # Second import with overlapping domains
    csv2 = "domain_name\nexample2.com\nexample3.com"
    response = await client.post(
        f"/api/v1/wizard/batches/{batch_id}/step1/import-domains",
        files={"file": ("domains.csv", csv2.encode(), "text/csv")},
        data={"redirect_url": "https://test.com"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["details"]["created"] == 1  # Only example3.com should be new
    assert data["details"]["skipped"] == 1  # example2.com should be skipped


@pytest.mark.asyncio
async def test_multiple_batches_independent(client: AsyncClient):
    """Test that multiple batches don't interfere with each other."""
    # Create two batches
    batch1_resp = await client.post(
        "/api/v1/wizard/batches",
        json={"name": "Batch 1"}
    )
    batch1_id = batch1_resp.json()["id"]
    
    batch2_resp = await client.post(
        "/api/v1/wizard/batches",
        json={"name": "Batch 2"}
    )
    batch2_id = batch2_resp.json()["id"]
    
    # Import domains to batch 1 only
    csv_content = "domain_name\nbatch1domain.com"
    await client.post(
        f"/api/v1/wizard/batches/{batch1_id}/step1/import-domains",
        files={"file": ("domains.csv", csv_content.encode(), "text/csv")},
        data={"redirect_url": "https://example.com"}
    )
    
    # Verify batch 1 has domain
    status1 = await client.get(f"/api/v1/wizard/batches/{batch1_id}/status")
    assert status1.json()["domains_total"] == 1
    
    # Verify batch 2 still has 0 domains
    status2 = await client.get(f"/api/v1/wizard/batches/{batch2_id}/status")
    assert status2.json()["domains_total"] == 0
    
    # Verify batch progresses are independent
    assert status1.json()["current_step"] == 2  # Batch 1 advanced
    assert status2.json()["current_step"] == 1  # Batch 2 still at step 1


@pytest.mark.asyncio
async def test_batch_isolation_with_pausing(client: AsyncClient):
    """Test that pausing one batch doesn't affect others."""
    # Create two batches
    batch1_resp = await client.post(
        "/api/v1/wizard/batches",
        json={"name": "Active Batch"}
    )
    batch1_id = batch1_resp.json()["id"]
    
    batch2_resp = await client.post(
        "/api/v1/wizard/batches",
        json={"name": "Paused Batch"}
    )
    batch2_id = batch2_resp.json()["id"]
    
    # Pause batch 2
    await client.patch(f"/api/v1/wizard/batches/{batch2_id}/pause")
    
    # Verify batch 1 is still active
    status1 = await client.get(f"/api/v1/wizard/batches/{batch1_id}/status")
    assert status1.json()["status"] == "active"
    
    # Verify batch 2 is paused
    status2 = await client.get(f"/api/v1/wizard/batches/{batch2_id}/status")
    assert status2.json()["status"] == "paused"


@pytest.mark.asyncio  
async def test_delete_batch(client: AsyncClient):
    """Test deleting a batch."""
    # Create batch
    create_resp = await client.post(
        "/api/v1/wizard/batches",
        json={"name": "Delete Test"}
    )
    batch_id = create_resp.json()["id"]
    
    # Verify it exists
    get_resp = await client.get(f"/api/v1/wizard/batches/{batch_id}")
    assert get_resp.status_code == 200
    
    # Delete it
    delete_resp = await client.delete(f"/api/v1/wizard/batches/{batch_id}")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["success"] is True
    
    # Verify it's gone
    status_resp = await client.get(f"/api/v1/wizard/batches/{batch_id}/status")
    assert status_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_nonexistent_batch(client: AsyncClient):
    """Test deleting a non-existent batch returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.delete(f"/api/v1/wizard/batches/{fake_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_legacy_status_endpoint(client: AsyncClient):
    """Test the legacy /status endpoint still works."""
    response = await client.get("/api/v1/wizard/status")
    assert response.status_code == 200
    data = response.json()
    assert "current_step" in data
    assert "step_name" in data
    assert "domains_total" in data
    assert "tenants_total" in data
    assert "mailboxes_total" in data


@pytest.mark.asyncio
async def test_batch_step_progression(client: AsyncClient):
    """Test that batch steps progress correctly."""
    # Create batch
    create_resp = await client.post(
        "/api/v1/wizard/batches",
        json={"name": "Progression Test"}
    )
    batch_id = create_resp.json()["id"]
    
    # Initially at step 1
    status1 = await client.get(f"/api/v1/wizard/batches/{batch_id}/status")
    assert status1.json()["current_step"] == 1
    assert status1.json()["step_name"] == "Import Domains"
    
    # Import domains
    csv = "domain_name\nprogression-test.com"
    await client.post(
        f"/api/v1/wizard/batches/{batch_id}/step1/import-domains",
        files={"file": ("domains.csv", csv.encode(), "text/csv")},
        data={"redirect_url": "https://test.com"}
    )
    
    # Should be at step 2
    status2 = await client.get(f"/api/v1/wizard/batches/{batch_id}/status")
    assert status2.json()["current_step"] == 2
    assert status2.json()["step_name"] == "Create Zones"