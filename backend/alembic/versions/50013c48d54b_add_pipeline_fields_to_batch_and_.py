"""add pipeline fields to batch and pipeline_log table

Revision ID: 50013c48d54b
Revises: 024_add_custom_mailbox_map
Create Date: 2026-02-25 17:07:43.132946

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '50013c48d54b'
down_revision: Union[str, None] = '024_add_custom_mailbox_map'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Create pipeline_logs table ---
    op.create_table('pipeline_logs',
        sa.Column('batch_id', sa.UUID(), nullable=False),
        sa.Column('step', sa.Integer(), nullable=False),
        sa.Column('step_name', sa.String(), nullable=False),
        sa.Column('item_type', sa.String(), nullable=True),
        sa.Column('item_id', sa.String(), nullable=True),
        sa.Column('item_name', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('message', sa.String(), nullable=True),
        sa.Column('error_detail', sa.Text(), nullable=True),
        sa.Column('retryable', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['batch_id'], ['setup_batches.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_pipeline_logs_batch_id'), 'pipeline_logs', ['batch_id'], unique=False)

    # --- Add new columns to setup_batches ---
    # Upfront collection fields
    op.add_column('setup_batches', sa.Column('new_admin_password', sa.String(), nullable=True))

    # Sequencer fields
    op.add_column('setup_batches', sa.Column('sequencer_platform', sa.String(), nullable=True))
    op.add_column('setup_batches', sa.Column('sequencer_login_email', sa.String(), nullable=True))
    op.add_column('setup_batches', sa.Column('sequencer_login_password', sa.String(), nullable=True))
    op.add_column('setup_batches', sa.Column('profile_photo_path', sa.String(), nullable=True))

    # Pipeline tracking
    op.add_column('setup_batches', sa.Column('pipeline_status', sa.String(), nullable=True, server_default='not_started'))
    op.add_column('setup_batches', sa.Column('pipeline_step', sa.Integer(), nullable=True, server_default='0'))
    op.add_column('setup_batches', sa.Column('pipeline_step_name', sa.String(), nullable=True))
    op.add_column('setup_batches', sa.Column('pipeline_started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('setup_batches', sa.Column('pipeline_completed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('setup_batches', sa.Column('pipeline_paused_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('setup_batches', sa.Column('ns_confirmed_at', sa.DateTime(timezone=True), nullable=True))

    # Aggregate progress counters (server_default for existing rows)
    op.add_column('setup_batches', sa.Column('total_domains', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('setup_batches', sa.Column('total_tenants', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('setup_batches', sa.Column('zones_completed', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('setup_batches', sa.Column('ns_propagated_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('setup_batches', sa.Column('dns_completed', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('setup_batches', sa.Column('first_login_completed_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('setup_batches', sa.Column('m365_completed', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('setup_batches', sa.Column('mailboxes_completed_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('setup_batches', sa.Column('smtp_completed', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('setup_batches', sa.Column('sequencer_uploaded_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('setup_batches', sa.Column('errors_count', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    # Drop new setup_batches columns
    op.drop_column('setup_batches', 'errors_count')
    op.drop_column('setup_batches', 'sequencer_uploaded_count')
    op.drop_column('setup_batches', 'smtp_completed')
    op.drop_column('setup_batches', 'mailboxes_completed_count')
    op.drop_column('setup_batches', 'm365_completed')
    op.drop_column('setup_batches', 'first_login_completed_count')
    op.drop_column('setup_batches', 'dns_completed')
    op.drop_column('setup_batches', 'ns_propagated_count')
    op.drop_column('setup_batches', 'zones_completed')
    op.drop_column('setup_batches', 'total_tenants')
    op.drop_column('setup_batches', 'total_domains')
    op.drop_column('setup_batches', 'ns_confirmed_at')
    op.drop_column('setup_batches', 'pipeline_paused_at')
    op.drop_column('setup_batches', 'pipeline_completed_at')
    op.drop_column('setup_batches', 'pipeline_started_at')
    op.drop_column('setup_batches', 'pipeline_step_name')
    op.drop_column('setup_batches', 'pipeline_step')
    op.drop_column('setup_batches', 'pipeline_status')
    op.drop_column('setup_batches', 'profile_photo_path')
    op.drop_column('setup_batches', 'sequencer_login_password')
    op.drop_column('setup_batches', 'sequencer_login_email')
    op.drop_column('setup_batches', 'sequencer_platform')
    op.drop_column('setup_batches', 'new_admin_password')

    # Drop pipeline_logs table
    op.drop_index(op.f('ix_pipeline_logs_batch_id'), table_name='pipeline_logs')
    op.drop_table('pipeline_logs')
