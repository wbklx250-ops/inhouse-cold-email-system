"""Add PlusVibe sequencer upload columns on mailboxes."""

from typing import Sequence, Union

from alembic import op

revision: str = "026_add_plusvibe_mailbox_columns"
down_revision: Union[str, None] = "025_add_skip_flags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE mailboxes ADD COLUMN IF NOT EXISTS plusvibe_uploaded BOOLEAN NOT NULL DEFAULT FALSE;"
    )
    op.execute(
        "ALTER TABLE mailboxes ADD COLUMN IF NOT EXISTS plusvibe_uploaded_at TIMESTAMP WITH TIME ZONE;"
    )
    op.execute(
        "ALTER TABLE mailboxes ADD COLUMN IF NOT EXISTS plusvibe_upload_error TEXT;"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE mailboxes DROP COLUMN IF EXISTS plusvibe_upload_error;")
    op.execute("ALTER TABLE mailboxes DROP COLUMN IF EXISTS plusvibe_uploaded_at;")
    op.execute("ALTER TABLE mailboxes DROP COLUMN IF EXISTS plusvibe_uploaded;")
