"""add_completed_steps_to_setup_batches

Revision ID: 41f54eb8b052
Revises: 010
Create Date: 2026-01-22 21:34:32.939618

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '41f54eb8b052'
down_revision: Union[str, None] = '010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add completed_steps column to setup_batches table
    op.add_column('setup_batches', sa.Column('completed_steps', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    # Remove completed_steps column
    op.drop_column('setup_batches', 'completed_steps')