"""Samples owned by a team

Revision ID: 0024
Revises: 0023

samples gets `owner_team_id`: a sample without an owner can belong to a team,
whose members then have owner rights over it (old samples imported without a
known researcher). Existing samples are unchanged.
"""
from alembic import op
import sqlalchemy as sa

revision = '0024'
down_revision = '0023'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('samples') as batch:
        batch.add_column(sa.Column('owner_team_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_samples_owner_team_id', 'teams', ['owner_team_id'], ['id'], ondelete='SET NULL')
        batch.create_index('ix_samples_owner_team_id', ['owner_team_id'])


def downgrade() -> None:
    with op.batch_alter_table('samples') as batch:
        batch.drop_index('ix_samples_owner_team_id')
        batch.drop_constraint('fk_samples_owner_team_id', type_='foreignkey')
        batch.drop_column('owner_team_id')
