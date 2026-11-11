"""A study's status: to do, ongoing or concluded

Revision ID: 0023
Revises: 0022

studies gets `status` ("todo" | "ongoing" | "concluded"); existing studies are ongoing.
"""
from alembic import op
import sqlalchemy as sa

revision = '0023'
down_revision = '0022'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('studies') as batch:
        batch.add_column(sa.Column('status', sa.String(10), server_default='ongoing', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('studies') as batch:
        batch.drop_column('status')
