"""add_step7_app_consent_fields

Revision ID: 018_step7_app_consent
Revises: 017_auto_progress_upload
Create Date: 2026-02-10

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "018_step7_app_consent"
down_revision = "017_auto_progress_upload"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("step7_app_consent_granted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "tenants",
        sa.Column("step7_app_consent_granted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("step7_app_consent_error", sa.Text(), nullable=True),
    )
    op.alter_column("tenants", "step7_app_consent_granted", server_default=None)


def downgrade() -> None:
    op.drop_column("tenants", "step7_app_consent_error")
    op.drop_column("tenants", "step7_app_consent_granted_at")
    op.drop_column("tenants", "step7_app_consent_granted")
