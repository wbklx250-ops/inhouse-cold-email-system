"""Add mailbox-level upload tracking fields.

Revision ID: 023_add_mailbox_upload_tracking
Revises: 022_auto_run_state
Create Date: 2026-02-19

Adds per-mailbox sequencer upload tracking:
- uploaded_to_sequencer (bool) - generic cross-sequencer flag
- uploaded_at (datetime) - when it was uploaded
- sequencer_name (string) - which sequencer it was uploaded to
- upload_error (text) - error message if upload failed
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '023_add_mailbox_upload_tracking'
down_revision: Union[str, None] = '022_auto_run_state'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('mailboxes', sa.Column('uploaded_to_sequencer', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('mailboxes', sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('mailboxes', sa.Column('sequencer_name', sa.String(100), nullable=True))
    op.add_column('mailboxes', sa.Column('upload_error', sa.Text(), nullable=True))

    # Add index for fast filtering of un-uploaded mailboxes
    op.create_index('ix_mailboxes_uploaded_to_sequencer', 'mailboxes', ['uploaded_to_sequencer'])
    op.create_index('ix_mailboxes_setup_complete', 'mailboxes', ['setup_complete'])


def downgrade() -> None:
    op.drop_index('ix_mailboxes_setup_complete', table_name='mailboxes')
    op.drop_index('ix_mailboxes_uploaded_to_sequencer', table_name='mailboxes')
    op.drop_column('mailboxes', 'upload_error')
    op.drop_column('mailboxes', 'sequencer_name')
    op.drop_column('mailboxes', 'uploaded_at')
    op.drop_column('mailboxes', 'uploaded_to_sequencer')
