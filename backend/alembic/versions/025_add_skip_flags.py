"""add skip flags to domains

Revision ID: 025_add_skip_flags
Revises: 50013c48d54b
Create Date: 2026-03-17

Add step5_skipped and step6_skipped boolean columns to domains table.
These flags are used when a domain exceeds MAX_PIPELINE_RETRIES so we can
skip it without lying about verification/completion status.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '025_add_skip_flags'
down_revision: Union[str, None] = '50013c48d54b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE domains ADD COLUMN IF NOT EXISTS step5_skipped BOOLEAN DEFAULT FALSE")
    op.execute("ALTER TABLE domains ADD COLUMN IF NOT EXISTS step6_skipped BOOLEAN DEFAULT FALSE")


def downgrade() -> None:
    op.execute("ALTER TABLE domains DROP COLUMN IF EXISTS step5_skipped")
    op.execute("ALTER TABLE domains DROP COLUMN IF EXISTS step6_skipped")
