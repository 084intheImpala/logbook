"""New samples are visible to the owner's team by default

Revision ID: 0017
Revises: 0016

Only the column's default changes: existing samples keep the visibility they have.
"""
from alembic import op

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("samples") as batch:
        batch.alter_column("visibility", server_default="team")


def downgrade():
    with op.batch_alter_table("samples") as batch:
        batch.alter_column("visibility", server_default="personal")
