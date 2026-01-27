"""Add Step 6 mailbox creation fields

Revision ID: 013
Revises: 012, 41f54eb8b052
Create Date: 2026-01-27

Adds fields needed for Step 6 (Mailbox Creation):
- Tenant: license_assigned, step6_* progress tracking fields
- SetupBatch: step6_emails_generated, step6_emails_generated_at
- Mailbox: local_part, created_in_exchange, display_name_fixed, setup_complete, etc.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '013'
down_revision = ('012', '41f54eb8b052')  # Merge both branches
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ============================================================================
    # TENANT TABLE: Add license_assigned and Step 6 tracking fields
    # ============================================================================
    
    # License tracking
    op.add_column('tenants', sa.Column('license_assigned', sa.Boolean(), nullable=False, server_default='false'))
    
    # Step 6 progress tracking
    op.add_column('tenants', sa.Column('step6_started', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('tenants', sa.Column('step6_started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('tenants', sa.Column('step6_mailboxes_created', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('tenants', sa.Column('step6_display_names_fixed', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('tenants', sa.Column('step6_accounts_enabled', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('tenants', sa.Column('step6_passwords_set', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('tenants', sa.Column('step6_upns_fixed', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('tenants', sa.Column('step6_delegations_done', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('tenants', sa.Column('step6_complete', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('tenants', sa.Column('step6_completed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('tenants', sa.Column('step6_error', sa.Text(), nullable=True))
    
    # ============================================================================
    # SETUP_BATCHES TABLE: Add Step 6 email generation tracking
    # ============================================================================
    
    op.add_column('setup_batches', sa.Column('step6_emails_generated', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('setup_batches', sa.Column('step6_emails_generated_at', sa.DateTime(timezone=True), nullable=True))
    
    # ============================================================================
    # MAILBOXES TABLE: Add Step 6 provisioning fields
    # ============================================================================
    
    op.add_column('mailboxes', sa.Column('local_part', sa.String(255), nullable=True))
    op.add_column('mailboxes', sa.Column('created_in_exchange', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('mailboxes', sa.Column('created_at_exchange', sa.DateTime(timezone=True), nullable=True))
    op.add_column('mailboxes', sa.Column('display_name_fixed', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('mailboxes', sa.Column('setup_complete', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('mailboxes', sa.Column('setup_completed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # Remove mailbox columns
    op.drop_column('mailboxes', 'setup_completed_at')
    op.drop_column('mailboxes', 'setup_complete')
    op.drop_column('mailboxes', 'display_name_fixed')
    op.drop_column('mailboxes', 'created_at_exchange')
    op.drop_column('mailboxes', 'created_in_exchange')
    op.drop_column('mailboxes', 'local_part')
    
    # Remove setup_batches columns
    op.drop_column('setup_batches', 'step6_emails_generated_at')
    op.drop_column('setup_batches', 'step6_emails_generated')
    
    # Remove tenant columns
    op.drop_column('tenants', 'step6_error')
    op.drop_column('tenants', 'step6_completed_at')
    op.drop_column('tenants', 'step6_complete')
    op.drop_column('tenants', 'step6_delegations_done')
    op.drop_column('tenants', 'step6_upns_fixed')
    op.drop_column('tenants', 'step6_passwords_set')
    op.drop_column('tenants', 'step6_accounts_enabled')
    op.drop_column('tenants', 'step6_display_names_fixed')
    op.drop_column('tenants', 'step6_mailboxes_created')
    op.drop_column('tenants', 'step6_started_at')
    op.drop_column('tenants', 'step6_started')
    op.drop_column('tenants', 'license_assigned')
