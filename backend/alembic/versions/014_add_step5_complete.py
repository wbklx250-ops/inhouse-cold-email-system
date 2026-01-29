"""add step5 complete tracking

Revision ID: 014_add_step5_complete
Revises: 41f54eb8b052
Create Date: 2026-01-30 08:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "014_add_step5_complete"
down_revision = "41f54eb8b052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("step5_complete", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("tenants", sa.Column("step5_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("tenants", "step5_complete", server_default=None)


def downgrade() -> None:
    op.drop_column("tenants", "step5_completed_at")
    op.drop_column("tenants", "step5_complete")