"""A sample marked missing or destroyed

Revision ID: 0026
Revises: 0025

samples gets `condition` ("missing" / "destroyed", null while the sample is
there), `condition_on` (since when) and `condition_note` (why, where it was
last seen). Existing samples are all there.
"""
from alembic import op
import sqlalchemy as sa

revision = '0026'
down_revision = '0025'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('samples') as batch:
        batch.add_column(sa.Column('condition', sa.String(10), nullable=True))
        batch.add_column(sa.Column('condition_on', sa.Date(), nullable=True))
        batch.add_column(sa.Column('condition_note', sa.Text(), nullable=True))
        batch.create_index('ix_samples_condition', ['condition'])


def downgrade() -> None:
    with op.batch_alter_table('samples') as batch:
        batch.drop_index('ix_samples_condition')
        batch.drop_column('condition_note')
        batch.drop_column('condition_on')
        batch.drop_column('condition')
