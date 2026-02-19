"""Add auto_run_state JSONB column to setup_batches for persisting auto-run job state.

Revision ID: 022_auto_run_state
Revises: 021_add_smartlead
Create Date: 2026-02-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '022_auto_run_state'
down_revision = '021_add_smartlead'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Single JSONB column stores the entire auto-run job state dict.
    # This allows the server to restore progress after a restart.
    op.add_column(
        'setup_batches',
        sa.Column('auto_run_state', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('setup_batches', 'auto_run_state')
