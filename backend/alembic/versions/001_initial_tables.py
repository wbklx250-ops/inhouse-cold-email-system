"""Initial tables

Revision ID: 001
Revises: 
Create Date: 2026-01-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enums using raw SQL (IF NOT EXISTS)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE domain_status AS ENUM (
                'purchased', 'cf_zone_pending', 'cf_zone_active', 'ns_updating',
                'ns_propagating', 'dns_configuring', 'pending_m365', 'pending_dkim',
                'active', 'problem', 'retired'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE tenant_status AS ENUM (
                'new', 'configuring', 'active', 'suspended', 'retired'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE mailbox_status AS ENUM (
                'created', 'configured', 'uploaded', 'warming', 'ready', 'suspended'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE warmup_stage AS ENUM (
                'none', 'early', 'ramping', 'mature', 'complete'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # Create tables using raw SQL (IF NOT EXISTS)
    op.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            microsoft_tenant_id VARCHAR(255) NOT NULL UNIQUE,
            name VARCHAR(255) NOT NULL,
            onmicrosoft_domain VARCHAR(255) NOT NULL UNIQUE,
            provider VARCHAR(255) NOT NULL,
            admin_email VARCHAR(255) NOT NULL,
            admin_password VARCHAR(255) NOT NULL,
            licensed_user_email VARCHAR(255) NOT NULL,
            status tenant_status NOT NULL,
            target_mailbox_count INTEGER NOT NULL DEFAULT 50,
            mailboxes_created INTEGER NOT NULL DEFAULT 0,
            mailboxes_configured INTEGER NOT NULL DEFAULT 0,
            domain_id UUID,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        );
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS domains (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(255) NOT NULL UNIQUE,
            tld VARCHAR(50) NOT NULL,
            status domain_status NOT NULL,
            cloudflare_zone_id VARCHAR(255),
            cloudflare_nameservers JSONB NOT NULL DEFAULT '[]',
            cloudflare_zone_status VARCHAR(50) NOT NULL,
            nameservers_updated BOOLEAN NOT NULL DEFAULT FALSE,
            nameservers_updated_at TIMESTAMP WITH TIME ZONE,
            dns_records_created BOOLEAN NOT NULL DEFAULT FALSE,
            mx_configured BOOLEAN NOT NULL DEFAULT FALSE,
            spf_configured BOOLEAN NOT NULL DEFAULT FALSE,
            dmarc_configured BOOLEAN NOT NULL DEFAULT FALSE,
            dkim_cnames_added BOOLEAN NOT NULL DEFAULT FALSE,
            dkim_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            dkim_selector1_cname VARCHAR(255),
            dkim_selector2_cname VARCHAR(255),
            tenant_id UUID REFERENCES tenants(id) ON DELETE SET NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        );
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS mailboxes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email VARCHAR(255) NOT NULL UNIQUE,
            display_name VARCHAR(255) NOT NULL,
            password VARCHAR(255) NOT NULL,
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            status mailbox_status NOT NULL,
            account_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            password_set BOOLEAN NOT NULL DEFAULT FALSE,
            upn_fixed BOOLEAN NOT NULL DEFAULT FALSE,
            delegated BOOLEAN NOT NULL DEFAULT FALSE,
            warmup_stage warmup_stage NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        );
    """)

    # Add foreign key for tenant.domain_id (if not exists)
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE tenants ADD CONSTRAINT fk_tenants_domain_id 
            FOREIGN KEY (domain_id) REFERENCES domains(id) ON DELETE SET NULL;
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # Create indexes (if not exist)
    op.execute("CREATE INDEX IF NOT EXISTS ix_domains_status ON domains(status);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tenants_status ON tenants(status);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tenants_provider ON tenants(provider);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_mailboxes_tenant_id ON mailboxes(tenant_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_mailboxes_status ON mailboxes(status);")


def downgrade() -> None:
    # Drop indexes
    op.execute('DROP INDEX IF EXISTS ix_mailboxes_status')
    op.execute('DROP INDEX IF EXISTS ix_mailboxes_tenant_id')
    op.execute('DROP INDEX IF EXISTS ix_tenants_provider')
    op.execute('DROP INDEX IF EXISTS ix_tenants_status')
    op.execute('DROP INDEX IF EXISTS ix_domains_status')

    # Drop foreign key
    op.execute('ALTER TABLE tenants DROP CONSTRAINT IF EXISTS fk_tenants_domain_id')

    # Drop tables
    op.execute('DROP TABLE IF EXISTS mailboxes')
    op.execute('DROP TABLE IF EXISTS domains')
    op.execute('DROP TABLE IF EXISTS tenants')

    # Drop enums
    op.execute('DROP TYPE IF EXISTS warmup_stage')
    op.execute('DROP TYPE IF EXISTS mailbox_status')
    op.execute('DROP TYPE IF EXISTS tenant_status')
    op.execute('DROP TYPE IF EXISTS domain_status')