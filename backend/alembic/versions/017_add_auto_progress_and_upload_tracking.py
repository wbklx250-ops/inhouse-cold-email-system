"""Add auto-progress and upload tracking fields.

Revision ID: 017_auto_progress_upload
Revises: 016_add_step8_security_defaults_fields
Create Date: 2026-02-06

Adds:
- SetupBatch: uploaded_to_sequencer, uploaded_at, auto_progress_enabled
- Tenant: step4_retry_count, step5_retry_count, step6_retry_count, step7_retry_count
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '017_auto_progress_upload'
down_revision = '016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add upload tracking to setup_batches
    op.add_column('setup_batches', sa.Column('uploaded_to_sequencer', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('setup_batches', sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('setup_batches', sa.Column('auto_progress_enabled', sa.Boolean(), nullable=False, server_default='false'))
    
    # Add retry count tracking to tenants (for auto-retry feature)
    op.add_column('tenants', sa.Column('step4_retry_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('tenants', sa.Column('step5_retry_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('tenants', sa.Column('step6_retry_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('tenants', sa.Column('step7_retry_count', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    # Remove from tenants
    op.drop_column('tenants', 'step7_retry_count')
    op.drop_column('tenants', 'step6_retry_count')
    op.drop_column('tenants', 'step5_retry_count')
    op.drop_column('tenants', 'step4_retry_count')
    
    # Remove from setup_batches
    op.drop_column('setup_batches', 'auto_progress_enabled')
    op.drop_column('setup_batches', 'uploaded_at')
    op.drop_column('setup_batches', 'uploaded_to_sequencer')
