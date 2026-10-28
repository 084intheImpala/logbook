"""equipment that only suits one method (e.g. AnnealSYS is RTA only)

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('choice_options', sa.Column('applies_to', sa.String(length=50), nullable=True))
    op.execute("UPDATE choice_options SET applies_to = 'RTA' "
               "WHERE list = 'annealing_equipment' AND lower(value) LIKE 'annealsys%'")


def downgrade() -> None:
    op.drop_column('choice_options', 'applies_to')
