"""Add custom_mailbox_map JSONB column to setup_batches.

Revision ID: 024_add_custom_mailbox_map
Revises: 023_add_mailbox_upload_tracking
Create Date: 2026-02-20

Allows importing pre-existing email addresses from CSV files
so domains that have been set up before can reuse the exact same
email addresses instead of generating new random ones.

The column stores a JSON map: {"domain.com": ["email1@domain.com", ...], ...}
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = '024_add_custom_mailbox_map'
down_revision: Union[str, None] = '023_add_mailbox_upload_tracking'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('setup_batches', sa.Column('custom_mailbox_map', JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column('setup_batches', 'custom_mailbox_map')
