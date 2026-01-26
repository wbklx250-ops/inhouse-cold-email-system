"""update_tenant_model_full_automation

Revision ID: 9a25dfed836a
Revises: 007
Create Date: 2026-01-20 19:41:00.393096

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a25dfed836a'
down_revision: Union[str, None] = '008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === ADD NEW COLUMNS TO TENANTS ===
    
    # Contact info from CSV
    op.add_column('tenants', sa.Column('address', sa.String(length=500), nullable=True))
    op.add_column('tenants', sa.Column('contact_name', sa.String(length=255), nullable=True))
    op.add_column('tenants', sa.Column('contact_email', sa.String(length=255), nullable=True))
    op.add_column('tenants', sa.Column('contact_phone', sa.String(length=50), nullable=True))
    
    # Admin credentials
    op.add_column('tenants', sa.Column('totp_secret', sa.String(length=255), nullable=True))
    
    # First login tracking
    op.add_column('tenants', sa.Column('first_login_completed', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('tenants', sa.Column('first_login_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('tenants', sa.Column('password_changed', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('tenants', sa.Column('security_defaults_disabled', sa.Boolean(), nullable=False, server_default='false'))
    
    # Licensed user (rename licensed_user_email -> licensed_user_upn)
    op.add_column('tenants', sa.Column('licensed_user_upn', sa.String(length=255), nullable=True))
    op.add_column('tenants', sa.Column('licensed_user_password', sa.String(length=255), nullable=True))
    op.add_column('tenants', sa.Column('licensed_user_created', sa.Boolean(), nullable=False, server_default='false'))
    
    # Migrate data from licensed_user_email to licensed_user_upn
    op.execute("UPDATE tenants SET licensed_user_upn = licensed_user_email")
    
    # Domain linking
    op.add_column('tenants', sa.Column('custom_domain', sa.String(length=255), nullable=True))
    
    # M365 domain setup
    op.add_column('tenants', sa.Column('domain_added_to_m365', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('tenants', sa.Column('m365_verification_txt', sa.String(length=255), nullable=True))
    op.add_column('tenants', sa.Column('domain_verified_in_m365', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('tenants', sa.Column('domain_verified_at', sa.DateTime(timezone=True), nullable=True))
    
    # DNS tracking
    op.add_column('tenants', sa.Column('mx_record_added', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('tenants', sa.Column('spf_record_added', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('tenants', sa.Column('autodiscover_added', sa.Boolean(), nullable=False, server_default='false'))
    
    # DKIM tracking
    op.add_column('tenants', sa.Column('dkim_selector1', sa.String(length=500), nullable=True))
    op.add_column('tenants', sa.Column('dkim_selector2', sa.String(length=500), nullable=True))
    op.add_column('tenants', sa.Column('dkim_cnames_added', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('tenants', sa.Column('dkim_enabled', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('tenants', sa.Column('dkim_enabled_at', sa.DateTime(timezone=True), nullable=True))
    
    # Mailbox tracking (rename mailboxes_created INT -> mailbox_count, add mailboxes_created BOOL)
    op.add_column('tenants', sa.Column('mailbox_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('tenants', sa.Column('mailboxes_generated', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('tenants', sa.Column('mailboxes_created_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('tenants', sa.Column('delegation_completed', sa.Boolean(), nullable=False, server_default='false'))
    
    # Migrate mailboxes_created (integer) to mailbox_count (integer)
    op.execute("UPDATE tenants SET mailbox_count = mailboxes_created")
    
    # Now handle the mailboxes_created column type change (INT -> BOOL)
    # Drop the old integer column and add as boolean
    op.drop_column('tenants', 'mailboxes_created')
    op.add_column('tenants', sa.Column('mailboxes_created', sa.Boolean(), nullable=False, server_default='false'))
    
    # Set mailboxes_created = true where mailbox_count > 0
    op.execute("UPDATE tenants SET mailboxes_created = true WHERE mailbox_count > 0")
    
    # Status/error (rename error_message -> setup_error)
    op.add_column('tenants', sa.Column('setup_error', sa.Text(), nullable=True))
    op.execute("UPDATE tenants SET setup_error = error_message")
    
    # Drop old columns
    op.drop_column('tenants', 'licensed_user_email')
    op.drop_column('tenants', 'error_message')
    
    # NOTE: Status value migration is handled in migration 009_migrate_tenant_status_values.py
    # This is because PostgreSQL requires new enum values to be committed before use


def downgrade() -> None:
    # Restore error_message column
    op.add_column('tenants', sa.Column('error_message', sa.VARCHAR(length=1000), autoincrement=False, nullable=True))
    op.execute("UPDATE tenants SET error_message = setup_error")
    
    # Restore licensed_user_email column
    op.add_column('tenants', sa.Column('licensed_user_email', sa.VARCHAR(length=255), autoincrement=False, nullable=False, server_default=''))
    op.execute("UPDATE tenants SET licensed_user_email = COALESCE(licensed_user_upn, '')")
    
    # Convert mailboxes_created back to integer
    op.drop_column('tenants', 'mailboxes_created')
    op.add_column('tenants', sa.Column('mailboxes_created', sa.INTEGER(), autoincrement=False, nullable=False, server_default='0'))
    op.execute("UPDATE tenants SET mailboxes_created = mailbox_count")
    
    # Drop all new columns
    op.drop_column('tenants', 'setup_error')
    op.drop_column('tenants', 'delegation_completed')
    op.drop_column('tenants', 'mailboxes_created_at')
    op.drop_column('tenants', 'mailboxes_generated')
    op.drop_column('tenants', 'mailbox_count')
    op.drop_column('tenants', 'dkim_enabled_at')
    op.drop_column('tenants', 'dkim_enabled')
    op.drop_column('tenants', 'dkim_cnames_added')
    op.drop_column('tenants', 'dkim_selector2')
    op.drop_column('tenants', 'dkim_selector1')
    op.drop_column('tenants', 'autodiscover_added')
    op.drop_column('tenants', 'spf_record_added')
    op.drop_column('tenants', 'mx_record_added')
    op.drop_column('tenants', 'domain_verified_at')
    op.drop_column('tenants', 'domain_verified_in_m365')
    op.drop_column('tenants', 'm365_verification_txt')
    op.drop_column('tenants', 'domain_added_to_m365')
    op.drop_column('tenants', 'custom_domain')
    op.drop_column('tenants', 'licensed_user_created')
    op.drop_column('tenants', 'licensed_user_password')
    op.drop_column('tenants', 'licensed_user_upn')
    op.drop_column('tenants', 'security_defaults_disabled')
    op.drop_column('tenants', 'password_changed')
    op.drop_column('tenants', 'first_login_at')
    op.drop_column('tenants', 'first_login_completed')
    op.drop_column('tenants', 'totp_secret')
    op.drop_column('tenants', 'contact_phone')
    op.drop_column('tenants', 'contact_email')
    op.drop_column('tenants', 'contact_name')
    op.drop_column('tenants', 'address')
    
    # Note: PostgreSQL doesn't support removing enum values easily
    # The old enum values will remain but won't be referenced