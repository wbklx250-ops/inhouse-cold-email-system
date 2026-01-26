"""add setup batch system

Revision ID: 007
Revises: 006_add_redirect_configured
Create Date: 2026-01-17

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create batch_status enum first
    batch_status = postgresql.ENUM('active', 'paused', 'completed', name='batch_status')
    batch_status.create(op.get_bind(), checkfirst=True)
    
    # Create setup_batches table
    op.create_table(
        'setup_batches',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('current_step', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', postgresql.ENUM('active', 'paused', 'completed', name='batch_status', create_type=False), nullable=False, server_default='active'),
        sa.Column('redirect_url', sa.String(500), nullable=True),
        sa.Column('persona_first_name', sa.String(100), nullable=True),
        sa.Column('persona_last_name', sa.String(100), nullable=True),
        sa.Column('mailboxes_per_tenant', sa.Integer(), nullable=False, server_default='50'),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    
    # Add batch_id to domains table
    op.add_column('domains', sa.Column('batch_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_domains_batch_id',
        'domains', 'setup_batches',
        ['batch_id'], ['id'],
        ondelete='SET NULL'
    )
    
    # Add batch_id to tenants table
    op.add_column('tenants', sa.Column('batch_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_tenants_batch_id',
        'tenants', 'setup_batches',
        ['batch_id'], ['id'],
        ondelete='SET NULL'
    )
    
    # Add batch_id to mailboxes table
    op.add_column('mailboxes', sa.Column('batch_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_mailboxes_batch_id',
        'mailboxes', 'setup_batches',
        ['batch_id'], ['id'],
        ondelete='SET NULL'
    )
    
    # Create indexes for batch_id lookups
    op.create_index('ix_domains_batch_id', 'domains', ['batch_id'])
    op.create_index('ix_tenants_batch_id', 'tenants', ['batch_id'])
    op.create_index('ix_mailboxes_batch_id', 'mailboxes', ['batch_id'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_mailboxes_batch_id', table_name='mailboxes')
    op.drop_index('ix_tenants_batch_id', table_name='tenants')
    op.drop_index('ix_domains_batch_id', table_name='domains')
    
    # Drop foreign keys
    op.drop_constraint('fk_mailboxes_batch_id', 'mailboxes', type_='foreignkey')
    op.drop_constraint('fk_tenants_batch_id', 'tenants', type_='foreignkey')
    op.drop_constraint('fk_domains_batch_id', 'domains', type_='foreignkey')
    
    # Drop batch_id columns
    op.drop_column('mailboxes', 'batch_id')
    op.drop_column('tenants', 'batch_id')
    op.drop_column('domains', 'batch_id')
    
    # Drop setup_batches table
    op.drop_table('setup_batches')
    
    # Drop batch_status enum
    sa.Enum(name='batch_status').drop(op.get_bind(), checkfirst=True)