"""Mailbox model updates - add M365 fields and fix columns

Revision ID: 004
Revises: 003
Create Date: 2025-01-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns for M365 integration
    op.add_column('mailboxes', sa.Column('microsoft_object_id', sa.String(255), nullable=True))
    op.add_column('mailboxes', sa.Column('upn', sa.String(255), nullable=True))
    op.add_column('mailboxes', sa.Column('photo_set', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('mailboxes', sa.Column('error_message', sa.Text(), nullable=True))
    
    # Fix password column to be nullable
    op.alter_column('mailboxes', 'password',
                    existing_type=sa.String(255),
                    nullable=True)
    
    # Fix account_enabled default to False
    op.alter_column('mailboxes', 'account_enabled',
                    existing_type=sa.Boolean(),
                    server_default='false')
    
    # Add new enum values to mailbox_status
    # PostgreSQL requires explicit ALTER TYPE for enum values
    op.execute("ALTER TYPE mailbox_status ADD VALUE IF NOT EXISTS 'pending'")
    op.execute("ALTER TYPE mailbox_status ADD VALUE IF NOT EXISTS 'enabled'")
    op.execute("ALTER TYPE mailbox_status ADD VALUE IF NOT EXISTS 'password_set'")
    op.execute("ALTER TYPE mailbox_status ADD VALUE IF NOT EXISTS 'upn_fixed'")
    op.execute("ALTER TYPE mailbox_status ADD VALUE IF NOT EXISTS 'delegated'")
    op.execute("ALTER TYPE mailbox_status ADD VALUE IF NOT EXISTS 'error'")


def downgrade() -> None:
    # Remove new columns
    op.drop_column('mailboxes', 'error_message')
    op.drop_column('mailboxes', 'photo_set')
    op.drop_column('mailboxes', 'upn')
    op.drop_column('mailboxes', 'microsoft_object_id')
    
    # Revert password to non-nullable (may fail if NULL values exist)
    op.alter_column('mailboxes', 'password',
                    existing_type=sa.String(255),
                    nullable=False)
    
    # Revert account_enabled default to True
    op.alter_column('mailboxes', 'account_enabled',
                    existing_type=sa.Boolean(),
                    server_default='true')
    
    # Note: PostgreSQL does not support removing enum values easily
    # The new enum values will remain in the type