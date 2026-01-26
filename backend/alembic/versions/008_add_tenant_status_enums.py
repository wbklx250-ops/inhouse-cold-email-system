"""add_tenant_status_enums

Revision ID: 008
Revises: 007
Create Date: 2026-01-20

This migration adds new enum values to tenant_status.
Must be run separately before the main model update to allow PostgreSQL to commit the enum changes.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '008'
down_revision: Union[str, None] = '007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new enum values (PostgreSQL)
    # These must be committed before they can be used in UPDATE statements
    op.execute("ALTER TYPE tenant_status ADD VALUE IF NOT EXISTS 'first_login_pending'")
    op.execute("ALTER TYPE tenant_status ADD VALUE IF NOT EXISTS 'first_login_complete'")
    op.execute("ALTER TYPE tenant_status ADD VALUE IF NOT EXISTS 'domain_added'")
    op.execute("ALTER TYPE tenant_status ADD VALUE IF NOT EXISTS 'dns_configured'")
    op.execute("ALTER TYPE tenant_status ADD VALUE IF NOT EXISTS 'mailboxes_created'")
    op.execute("ALTER TYPE tenant_status ADD VALUE IF NOT EXISTS 'ready'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values easily
    # The old enum values will remain but won't be referenced
    pass