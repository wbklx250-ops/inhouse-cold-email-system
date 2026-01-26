"""add_oauth_and_setup_step_fields

Revision ID: 010
Revises: 009
Create Date: 2026-01-22

Add OAuth token fields and setup_step for tenant automation progress tracking.
These fields are required for the orchestrator to:
- Store OAuth tokens after first login
- Track current automation step for debugging
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '010'
down_revision: Union[str, None] = '009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === ADD OAUTH TOKEN COLUMNS ===
    op.add_column('tenants', sa.Column('access_token', sa.Text(), nullable=True))
    op.add_column('tenants', sa.Column('refresh_token', sa.Text(), nullable=True))
    op.add_column('tenants', sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True))
    
    # === ADD DEBUG TRACKING COLUMN ===
    op.add_column('tenants', sa.Column('setup_step', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('tenants', 'setup_step')
    op.drop_column('tenants', 'token_expires_at')
    op.drop_column('tenants', 'refresh_token')
    op.drop_column('tenants', 'access_token')