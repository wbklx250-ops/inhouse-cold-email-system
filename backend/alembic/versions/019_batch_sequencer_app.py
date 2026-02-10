"""add_batch_sequencer_app

Revision ID: 019_batch_sequencer_app
Revises: 018_step7_app_consent
Create Date: 2026-02-10

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "019_batch_sequencer_app"
down_revision = "018_step7_app_consent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "setup_batches",
        sa.Column(
            "sequencer_app_key",
            sa.String(length=50),
            nullable=False,
            server_default="instantly",
        ),
    )
    op.alter_column("setup_batches", "sequencer_app_key", server_default=None)


def downgrade() -> None:
    op.drop_column("setup_batches", "sequencer_app_key")
