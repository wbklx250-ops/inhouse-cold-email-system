"""Add redirect_configured column to domains table

Revision ID: 006
Revises: 005
Create Date: 2025-01-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add redirect_configured column to track if Cloudflare redirect rule has been set up
    op.add_column('domains', sa.Column('redirect_configured', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('domains', 'redirect_configured')