"""Add Step 5 bulletproof tracking columns (dns_configured, permanently_failed)

Revision ID: 025
Revises: 024
Create Date: 2026-02-20
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "025"
down_revision = "024_add_custom_mailbox_map"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add dns_configured column
    op.add_column(
        "tenants",
        sa.Column("dns_configured", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    # Add permanently_failed column
    op.add_column(
        "tenants",
        sa.Column("permanently_failed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("tenants", "permanently_failed")
    op.drop_column("tenants", "dns_configured")
