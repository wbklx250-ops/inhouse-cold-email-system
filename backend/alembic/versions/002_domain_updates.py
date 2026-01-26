"""Add domain phase tracking and M365 verification fields

Revision ID: 002
Revises: 001
Create Date: 2026-01-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new enum values to domain_status
    # PostgreSQL allows adding enum values with ALTER TYPE
    op.execute("ALTER TYPE domain_status ADD VALUE IF NOT EXISTS 'zone_created';")
    op.execute("ALTER TYPE domain_status ADD VALUE IF NOT EXISTS 'ns_propagated';")
    op.execute("ALTER TYPE domain_status ADD VALUE IF NOT EXISTS 'tenant_linked';")
    op.execute("ALTER TYPE domain_status ADD VALUE IF NOT EXISTS 'm365_verified';")
    op.execute("ALTER TYPE domain_status ADD VALUE IF NOT EXISTS 'error';")

    # Add new columns to domains table (using IF NOT EXISTS pattern)
    op.execute("""
        ALTER TABLE domains 
        ADD COLUMN IF NOT EXISTS phase1_cname_added BOOLEAN NOT NULL DEFAULT FALSE;
    """)
    
    op.execute("""
        ALTER TABLE domains 
        ADD COLUMN IF NOT EXISTS phase1_dmarc_added BOOLEAN NOT NULL DEFAULT FALSE;
    """)
    
    op.execute("""
        ALTER TABLE domains 
        ADD COLUMN IF NOT EXISTS verification_txt_value VARCHAR(255);
    """)
    
    op.execute("""
        ALTER TABLE domains 
        ADD COLUMN IF NOT EXISTS verification_txt_added BOOLEAN NOT NULL DEFAULT FALSE;
    """)
    
    op.execute("""
        ALTER TABLE domains 
        ADD COLUMN IF NOT EXISTS error_message VARCHAR(1000);
    """)
    
    op.execute("""
        ALTER TABLE domains 
        ADD COLUMN IF NOT EXISTS ns_propagated_at TIMESTAMP WITH TIME ZONE;
    """)
    
    op.execute("""
        ALTER TABLE domains 
        ADD COLUMN IF NOT EXISTS m365_verified_at TIMESTAMP WITH TIME ZONE;
    """)


def downgrade() -> None:
    # Drop columns (in reverse order of creation)
    op.execute("ALTER TABLE domains DROP COLUMN IF EXISTS m365_verified_at;")
    op.execute("ALTER TABLE domains DROP COLUMN IF EXISTS ns_propagated_at;")
    op.execute("ALTER TABLE domains DROP COLUMN IF EXISTS error_message;")
    op.execute("ALTER TABLE domains DROP COLUMN IF EXISTS verification_txt_added;")
    op.execute("ALTER TABLE domains DROP COLUMN IF EXISTS verification_txt_value;")
    op.execute("ALTER TABLE domains DROP COLUMN IF EXISTS phase1_dmarc_added;")
    op.execute("ALTER TABLE domains DROP COLUMN IF EXISTS phase1_cname_added;")
    
    # Note: PostgreSQL doesn't support removing enum values easily
    # The enum values will remain but won't cause issues