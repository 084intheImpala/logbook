"""A study's code repository and its publications

Revision ID: 0025
Revises: 0024

studies gets `repo_url` (e.g. the GitHub repository with the analysis code);
study_references gets `published`: true for a paper that uses the study's data
(listed as the study's publications), false for a reference. Existing
references stay references.
"""
from alembic import op
import sqlalchemy as sa

revision = '0025'
down_revision = '0024'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('studies') as batch:
        batch.add_column(sa.Column('repo_url', sa.String(500), nullable=True))
    with op.batch_alter_table('study_references') as batch:
        batch.add_column(sa.Column('published', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('study_references') as batch:
        batch.drop_column('published')
    with op.batch_alter_table('studies') as batch:
        batch.drop_column('repo_url')
