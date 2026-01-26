"""add_initial_password_to_tenants

Revision ID: 011
Revises: 010
Create Date: 2026-01-22

Add initial_password field to store the original reseller password.
This enables resumable automation - if automation crashes after password change
but before MFA setup, the next run can use the new password (admin_password)
while initial_password remains unchanged as a fallback.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '011'
down_revision: Union[str, None] = '41f54eb8b052'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add initial_password column
    op.add_column('tenants', sa.Column('initial_password', sa.String(length=255), nullable=True))
    
    # Copy current admin_password to initial_password for existing records
    # This preserves the original password for tenants that haven't been processed yet
    # For tenants already processed (password_changed=true), this gives us a fallback
    op.execute("""
        UPDATE tenants 
        SET initial_password = admin_password 
        WHERE initial_password IS NULL
    """)


def downgrade() -> None:
    op.drop_column('tenants', 'initial_password')