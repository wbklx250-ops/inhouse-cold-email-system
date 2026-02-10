"""add_step8_security_defaults_fields

Revision ID: 016_add_step8_security_defaults_fields
Revises: 015_add_step7_sequencer_prep_fields
Create Date: 2026-02-04 20:38:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "016"  # Shortened to fit VARCHAR(32)
down_revision = ("015_add_step7_sequencer_prep_fie", "013")  # Merge both branches
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Note: security_defaults_disabled column already exists in the model
    # Only adding the error and timestamp columns
    op.add_column(
        "tenants",
        sa.Column("security_defaults_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("security_defaults_disabled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenants", "security_defaults_disabled_at")
    op.drop_column("tenants", "security_defaults_error")
