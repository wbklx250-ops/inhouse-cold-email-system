"""add_step7_sequencer_prep_fields

Revision ID: 015_add_step7_sequencer_prep_fields
Revises: 014_add_step5_complete
Create Date: 2026-02-02 02:22:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "015_add_step7_sequencer_prep_fields"
down_revision = "014_add_step5_complete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("step7_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "tenants",
        sa.Column("step7_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "step7_smtp_auth_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "tenants",
        sa.Column("step7_error", sa.Text(), nullable=True),
    )
    op.alter_column("tenants", "step7_complete", server_default=None)
    op.alter_column("tenants", "step7_smtp_auth_enabled", server_default=None)


def downgrade() -> None:
    op.drop_column("tenants", "step7_error")
    op.drop_column("tenants", "step7_smtp_auth_enabled")
    op.drop_column("tenants", "step7_completed_at")
    op.drop_column("tenants", "step7_complete")