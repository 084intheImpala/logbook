"""Study notes can be about one of the study's references

Revision ID: 0022
Revises: 0021

study_notes gets `reference_id` (a StudyReference of the same study; set to
null when the reference is removed).
"""
from alembic import op
import sqlalchemy as sa

revision = '0022'
down_revision = '0021'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('study_notes') as batch:
        batch.add_column(sa.Column('reference_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_study_notes_reference_id', 'study_references', ['reference_id'], ['id'],
                                 ondelete='SET NULL')


def downgrade() -> None:
    with op.batch_alter_table('study_notes') as batch:
        batch.drop_constraint('fk_study_notes_reference_id', type_='foreignkey')
        batch.drop_column('reference_id')
