"""Add PENDING_DKIM status and DKIM retry tracking fields

Revision ID: 012
Revises: 011_add_initial_password_to_tenants
Create Date: 2026-01-25

Adds:
- 'pending_dkim' value to tenant_status enum
- dkim_retry_count field to track retry attempts
- dkim_last_retry_at field to track last retry timestamp
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add 'pending_dkim' to tenant_status enum
    # PostgreSQL requires ALTER TYPE to add enum values
    op.execute("ALTER TYPE tenant_status ADD VALUE IF NOT EXISTS 'pending_dkim' AFTER 'dns_configured'")
    
    # Add dkim_retry_count column
    op.add_column('tenants', sa.Column('dkim_retry_count', sa.Integer(), nullable=False, server_default='0'))
    
    # Add dkim_last_retry_at column
    op.add_column('tenants', sa.Column('dkim_last_retry_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # Remove the new columns
    op.drop_column('tenants', 'dkim_last_retry_at')
    op.drop_column('tenants', 'dkim_retry_count')
    
    # Note: PostgreSQL doesn't support removing enum values easily
    # Would need to recreate the enum type entirely
    # For simplicity, we just leave the enum value in place on downgrade