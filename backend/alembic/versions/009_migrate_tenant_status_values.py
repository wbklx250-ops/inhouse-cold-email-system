"""migrate_tenant_status_values

Revision ID: 009
Revises: 9a25dfed836a
Create Date: 2026-01-20

This migration updates existing tenant status values to use the new enum values.
It must run AFTER the enum values have been committed (migration 008).
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '009'
down_revision: Union[str, None] = '9a25dfed836a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Migrate existing status values to new ones
    # Map old statuses to new setup-focused statuses
    
    # 'new' and 'imported' stay as 'imported'
    op.execute("UPDATE tenants SET status = 'imported' WHERE status = 'new'")
    
    # 'active', 'configuring', 'mailboxes_configuring' become 'ready'
    op.execute("UPDATE tenants SET status = 'ready' WHERE status = 'active'")
    op.execute("UPDATE tenants SET status = 'ready' WHERE status = 'configuring'")
    op.execute("UPDATE tenants SET status = 'ready' WHERE status = 'mailboxes_configuring'")
    op.execute("UPDATE tenants SET status = 'ready' WHERE status = 'mailboxes_creating'")
    
    # Keep 'error', 'domain_verified', 'dkim_enabled' as they exist in new enum
    # 'domain_linked' -> 'domain_added' 
    op.execute("UPDATE tenants SET status = 'domain_added' WHERE status = 'domain_linked'")
    
    # 'm365_connected' -> 'first_login_complete'
    op.execute("UPDATE tenants SET status = 'first_login_complete' WHERE status = 'm365_connected'")
    
    # 'dns_configuring' -> 'dns_configured'
    op.execute("UPDATE tenants SET status = 'dns_configured' WHERE status = 'dns_configuring'")
    
    # 'dkim_configuring' -> 'dkim_enabled'
    op.execute("UPDATE tenants SET status = 'dkim_enabled' WHERE status = 'dkim_configuring'")
    
    # Handle suspended/retired -> error with note
    op.execute("UPDATE tenants SET status = 'error', setup_error = 'Previously suspended/retired' WHERE status = 'suspended'")
    op.execute("UPDATE tenants SET status = 'error', setup_error = 'Previously suspended/retired' WHERE status = 'retired'")


def downgrade() -> None:
    # Reverse mappings where possible
    op.execute("UPDATE tenants SET status = 'active' WHERE status = 'ready'")
    op.execute("UPDATE tenants SET status = 'domain_linked' WHERE status = 'domain_added'")
    op.execute("UPDATE tenants SET status = 'm365_connected' WHERE status = 'first_login_complete'")
    op.execute("UPDATE tenants SET status = 'dns_configuring' WHERE status = 'dns_configured'")
    op.execute("UPDATE tenants SET status = 'dkim_configuring' WHERE status = 'dkim_enabled'")
    # Note: first_login_pending, mailboxes_created don't have direct mappings