"""Add redirect_url column to domains table

Revision ID: 005
Revises: 004
Create Date: 2025-01-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add redirect_url column for cold email domains redirecting to main business website
    op.add_column('domains', sa.Column('redirect_url', sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column('domains', 'redirect_url')