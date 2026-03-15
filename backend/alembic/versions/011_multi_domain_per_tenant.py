"""multi_domain_per_tenant

Revision ID: 011
Revises: 010
Create Date: 2026-03-13

Support N domains per tenant (1, 2, or 3). Move per-domain M365/DNS/DKIM/licensed-user
tracking from tenants table to domains table so each domain tracks its own setup state.
For backwards compatibility, copy existing tenant values into the linked domain row.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '011'
down_revision: Union[str, None] = '010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =====================================================================
    # 1. ADD NEW COLUMNS TO domains TABLE
    # =====================================================================

    # Position of this domain within its tenant group (0, 1, 2)
    op.add_column('domains', sa.Column('domain_index_in_tenant', sa.Integer(), nullable=False, server_default='0'))

    # M365 domain setup tracking (moved from tenants)
    op.add_column('domains', sa.Column('domain_added_to_m365', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('domains', sa.Column('m365_verification_txt', sa.String(length=500), nullable=True))
    op.add_column('domains', sa.Column('domain_verified_in_m365', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('domains', sa.Column('domain_verified_at', sa.DateTime(timezone=True), nullable=True))

    # DNS tracking (moved from tenants)
    op.add_column('domains', sa.Column('mx_record_added', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('domains', sa.Column('spf_record_added', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('domains', sa.Column('autodiscover_added', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('domains', sa.Column('mx_value', sa.String(length=500), nullable=True))
    op.add_column('domains', sa.Column('spf_value', sa.String(length=500), nullable=True))

    # DKIM selectors (moved from tenants — the CNAME columns already exist on domains but at VARCHAR(255))
    op.add_column('domains', sa.Column('dkim_selector1', sa.String(length=500), nullable=True))
    op.add_column('domains', sa.Column('dkim_selector2', sa.String(length=500), nullable=True))
    op.add_column('domains', sa.Column('dkim_enabled_at', sa.DateTime(timezone=True), nullable=True))

    # Step 5 tracking (moved from tenants)
    op.add_column('domains', sa.Column('step5_complete', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('domains', sa.Column('step5_retry_count', sa.Integer(), nullable=False, server_default='0'))

    # Licensed user per domain (moved from tenants)
    op.add_column('domains', sa.Column('licensed_user_upn', sa.String(length=255), nullable=True))
    op.add_column('domains', sa.Column('licensed_user_password', sa.String(length=255), nullable=True))
    op.add_column('domains', sa.Column('licensed_user_created', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('domains', sa.Column('licensed_user_id', sa.String(length=255), nullable=True))

    # Step 6 tracking per domain (moved from tenants)
    op.add_column('domains', sa.Column('step6_complete', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('domains', sa.Column('step6_mailboxes_created', sa.Integer(), nullable=False, server_default='0'))

    # =====================================================================
    # 2. ALTER EXISTING COLUMNS ON domains TABLE
    #    dkim_selector1_cname and dkim_selector2_cname: VARCHAR(255) → VARCHAR(500)
    # =====================================================================
    op.alter_column('domains', 'dkim_selector1_cname',
                    existing_type=sa.String(length=255),
                    type_=sa.String(length=500),
                    existing_nullable=True)
    op.alter_column('domains', 'dkim_selector2_cname',
                    existing_type=sa.String(length=255),
                    type_=sa.String(length=500),
                    existing_nullable=True)

    # =====================================================================
    # 3. ADD domains_per_tenant TO setup_batches TABLE
    # =====================================================================
    op.add_column('setup_batches', sa.Column('domains_per_tenant', sa.Integer(), nullable=False, server_default='1'))

    # =====================================================================
    # 4. BACKFILL: Copy existing tenant data into linked domain rows
    #    For backwards compatibility, any domain that is already linked to a
    #    tenant gets its M365/DNS/DKIM/licensed-user state copied over.
    # =====================================================================
    op.execute("""
        UPDATE domains d
        SET
            domain_added_to_m365     = t.domain_added_to_m365,
            m365_verification_txt    = t.m365_verification_txt,
            domain_verified_in_m365  = t.domain_verified_in_m365,
            domain_verified_at       = t.domain_verified_at,
            mx_record_added          = t.mx_record_added,
            spf_record_added         = t.spf_record_added,
            autodiscover_added       = t.autodiscover_added,
            mx_value                 = t.mx_value,
            spf_value                = t.spf_value,
            dkim_selector1           = t.dkim_selector1,
            dkim_selector2           = t.dkim_selector2,
            dkim_selector1_cname     = t.dkim_selector1_cname,
            dkim_selector2_cname     = t.dkim_selector2_cname,
            dkim_cnames_added        = t.dkim_cnames_added,
            dkim_enabled             = t.dkim_enabled,
            dkim_enabled_at          = t.dkim_enabled_at,
            step5_complete           = t.step5_complete,
            step5_retry_count        = t.step5_retry_count,
            licensed_user_upn        = t.licensed_user_upn,
            licensed_user_password   = t.licensed_user_password,
            licensed_user_created    = t.licensed_user_created,
            licensed_user_id         = t.licensed_user_id,
            step6_complete           = t.step6_complete,
            step6_mailboxes_created  = t.step6_mailboxes_created
        FROM tenants t
        WHERE d.tenant_id = t.id
    """)


def downgrade() -> None:
    # =====================================================================
    # Reverse: drop new columns, revert altered columns, drop batch column
    # =====================================================================

    # Drop domains_per_tenant from setup_batches
    op.drop_column('setup_batches', 'domains_per_tenant')

    # Revert dkim CNAME columns back to VARCHAR(255)
    op.alter_column('domains', 'dkim_selector1_cname',
                    existing_type=sa.String(length=500),
                    type_=sa.String(length=255),
                    existing_nullable=True)
    op.alter_column('domains', 'dkim_selector2_cname',
                    existing_type=sa.String(length=500),
                    type_=sa.String(length=255),
                    existing_nullable=True)

    # Drop all new columns from domains (reverse order of addition)
    op.drop_column('domains', 'step6_mailboxes_created')
    op.drop_column('domains', 'step6_complete')
    op.drop_column('domains', 'licensed_user_id')
    op.drop_column('domains', 'licensed_user_created')
    op.drop_column('domains', 'licensed_user_password')
    op.drop_column('domains', 'licensed_user_upn')
    op.drop_column('domains', 'step5_retry_count')
    op.drop_column('domains', 'step5_complete')
    op.drop_column('domains', 'dkim_enabled_at')
    op.drop_column('domains', 'dkim_selector2')
    op.drop_column('domains', 'dkim_selector1')
    op.drop_column('domains', 'spf_value')
    op.drop_column('domains', 'mx_value')
    op.drop_column('domains', 'autodiscover_added')
    op.drop_column('domains', 'spf_record_added')
    op.drop_column('domains', 'mx_record_added')
    op.drop_column('domains', 'domain_verified_at')
    op.drop_column('domains', 'domain_verified_in_m365')
    op.drop_column('domains', 'm365_verification_txt')
    op.drop_column('domains', 'domain_added_to_m365')
    op.drop_column('domains', 'domain_index_in_tenant')
