"""Attachments remember a hash of their file's content

Revision ID: 0015
Revises: 0014

An upload identical to a file already stored points at that file instead of
storing it again (utils.save_upload). Files stored before this get their hash
from `python -m backend.dedupe_files`, which also merges the duplicates
already on disk; the migration doesn't read uploads/.
"""
from alembic import op
import sqlalchemy as sa

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("attachments", sa.Column("sha256", sa.String(length=64), nullable=True))
    op.create_index("ix_attachments_sha256", "attachments", ["sha256"])


def downgrade() -> None:
    op.drop_index("ix_attachments_sha256", table_name="attachments")
    op.drop_column("attachments", "sha256")
