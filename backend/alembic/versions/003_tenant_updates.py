"""Add tenant M365 integration fields and update status enum

Revision ID: 003
Revises: 002
Create Date: 2026-01-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new enum values to tenant_status
    # PostgreSQL allows adding enum values with ALTER TYPE
    op.execute("ALTER TYPE tenant_status ADD VALUE IF NOT EXISTS 'imported';")
    op.execute("ALTER TYPE tenant_status ADD VALUE IF NOT EXISTS 'domain_linked';")
    op.execute("ALTER TYPE tenant_status ADD VALUE IF NOT EXISTS 'm365_connected';")
    op.execute("ALTER TYPE tenant_status ADD VALUE IF NOT EXISTS 'domain_verified';")
    op.execute("ALTER TYPE tenant_status ADD VALUE IF NOT EXISTS 'dns_configuring';")
    op.execute("ALTER TYPE tenant_status ADD VALUE IF NOT EXISTS 'dkim_configuring';")
    op.execute("ALTER TYPE tenant_status ADD VALUE IF NOT EXISTS 'dkim_enabled';")
    op.execute("ALTER TYPE tenant_status ADD VALUE IF NOT EXISTS 'mailboxes_creating';")
    op.execute("ALTER TYPE tenant_status ADD VALUE IF NOT EXISTS 'mailboxes_configuring';")
    op.execute("ALTER TYPE tenant_status ADD VALUE IF NOT EXISTS 'error';")

    # Add new columns to tenants table (using IF NOT EXISTS pattern)
    op.execute("""
        ALTER TABLE tenants 
        ADD COLUMN IF NOT EXISTS licensed_user_id VARCHAR(255);
    """)
    
    op.execute("""
        ALTER TABLE tenants 
        ADD COLUMN IF NOT EXISTS provider_order_id VARCHAR(255);
    """)
    
    op.execute("""
        ALTER TABLE tenants 
        ADD COLUMN IF NOT EXISTS mx_value VARCHAR(500);
    """)
    
    op.execute("""
        ALTER TABLE tenants 
        ADD COLUMN IF NOT EXISTS spf_value VARCHAR(500);
    """)
    
    op.execute("""
        ALTER TABLE tenants 
        ADD COLUMN IF NOT EXISTS dkim_selector1_cname VARCHAR(500);
    """)
    
    op.execute("""
        ALTER TABLE tenants 
        ADD COLUMN IF NOT EXISTS dkim_selector2_cname VARCHAR(500);
    """)
    
    op.execute("""
        ALTER TABLE tenants 
        ADD COLUMN IF NOT EXISTS error_message VARCHAR(1000);
    """)


def downgrade() -> None:
    # Drop columns (in reverse order of creation)
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS error_message;")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS dkim_selector2_cname;")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS dkim_selector1_cname;")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS spf_value;")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS mx_value;")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS provider_order_id;")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS licensed_user_id;")
    
    # Note: PostgreSQL doesn't support removing enum values easily
    # The enum values will remain but won't cause issues