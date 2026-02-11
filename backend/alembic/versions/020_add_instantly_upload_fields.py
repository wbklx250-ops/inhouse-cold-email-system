"""add_instantly_upload_fields

Revision ID: 020_add_instantly_upload_fields
Revises: 019_batch_sequencer_app
Create Date: 2026-02-11

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = "020_add_instantly_upload_fields"
down_revision = "019_batch_sequencer_app"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create instantly_accounts table
    op.create_table(
        "instantly_accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("password", sa.String(length=255), nullable=False),
        sa.Column("api_key", sa.String(length=255), nullable=True),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_instantly_accounts_email", "instantly_accounts", ["email"], unique=True
    )

    # Add Instantly fields to mailboxes table
    op.add_column(
        "mailboxes",
        sa.Column(
            "instantly_uploaded",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "mailboxes",
        sa.Column("instantly_upload_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "mailboxes",
        sa.Column("instantly_uploaded_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Add Instantly fields to setup_batches table
    op.add_column(
        "setup_batches",
        sa.Column("instantly_email", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "setup_batches",
        sa.Column("instantly_api_key", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    # Remove columns from setup_batches
    op.drop_column("setup_batches", "instantly_api_key")
    op.drop_column("setup_batches", "instantly_email")

    # Remove columns from mailboxes
    op.drop_column("mailboxes", "instantly_uploaded_at")
    op.drop_column("mailboxes", "instantly_upload_error")
    op.drop_column("mailboxes", "instantly_uploaded")

    # Drop instantly_accounts table
    op.drop_index("ix_instantly_accounts_email", table_name="instantly_accounts")
    op.drop_table("instantly_accounts")
