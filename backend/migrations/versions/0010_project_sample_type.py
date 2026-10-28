"""commercial and collaboration samples become one 'project' type

Revision ID: 0010
Revises: 0009
"""
from alembic import op


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Commercial samples keep their ID, supplier and spec sheet; they have no
    # project yet, so the next edit asks for one (a project can be a supplier).
    op.execute("UPDATE samples SET sample_type = 'project' WHERE sample_type IN ('commercial', 'collaboration')")


def downgrade() -> None:
    op.execute("UPDATE samples SET sample_type = 'collaboration' WHERE sample_type = 'project' AND project_id IS NOT NULL")
    op.execute("UPDATE samples SET sample_type = 'commercial' WHERE sample_type = 'project'")
