"""Add Smartlead upload tracking fields to Mailbox

Revision ID: 021_add_smartlead
Revises: 020_add_instantly_upload_fields
Create Date: 2026-02-12 16:14:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '021_add_smartlead'
down_revision = '020_add_instantly_upload_fields'
branch_labels = None
depends_on = None


def upgrade():
    # Add Smartlead upload tracking fields to mailboxes table
    op.add_column('mailboxes', sa.Column('smartlead_uploaded', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('mailboxes', sa.Column('smartlead_uploaded_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('mailboxes', sa.Column('smartlead_upload_error', sa.Text(), nullable=True))
    
    # Add initial_password field for mailbox uploaders
    op.add_column('mailboxes', sa.Column('initial_password', sa.String(length=255), nullable=True))


def downgrade():
    # Remove Smartlead upload fields
    op.drop_column('mailboxes', 'initial_password')
    op.drop_column('mailboxes', 'smartlead_upload_error')
    op.drop_column('mailboxes', 'smartlead_uploaded_at')
    op.drop_column('mailboxes', 'smartlead_uploaded')
