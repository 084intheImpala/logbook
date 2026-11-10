"""Studies: several samples, references and dated notes, with co-owners

Revision ID: 0020
Revises: 0019

New tables: studies, study_owners (its co-owners), study_samples (which
samples it uses; a sample can be in several), study_references (papers by
DOI, or links) and study_notes (dated, ordered notes that can point at a
sample, step or analysis).
"""
from alembic import op
import sqlalchemy as sa

revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None

_NOW = sa.text('(CURRENT_TIMESTAMP)')


def upgrade() -> None:
    op.create_table(
        'studies',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('visibility', sa.String(10), server_default='team', nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=_NOW, nullable=False),
    )
    op.create_table(
        'study_owners',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('study_id', sa.Integer(), sa.ForeignKey('studies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.UniqueConstraint('study_id', 'user_id'),
    )
    op.create_index('ix_study_owners_study_id', 'study_owners', ['study_id'])
    op.create_index('ix_study_owners_user_id', 'study_owners', ['user_id'])
    op.create_table(
        'study_samples',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('study_id', sa.Integer(), sa.ForeignKey('studies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sample_id', sa.Integer(), sa.ForeignKey('samples.id', ondelete='CASCADE'), nullable=False),
        sa.Column('added_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=_NOW, nullable=False),
        sa.UniqueConstraint('study_id', 'sample_id'),
    )
    op.create_index('ix_study_samples_study_id', 'study_samples', ['study_id'])
    op.create_index('ix_study_samples_sample_id', 'study_samples', ['sample_id'])
    op.create_table(
        'study_references',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('study_id', sa.Integer(), sa.ForeignKey('studies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('doi', sa.String(200), nullable=True),
        sa.Column('url', sa.String(500), nullable=True),
        sa.Column('title', sa.String(500), nullable=True),
        sa.Column('authors', sa.String(500), nullable=True),
        sa.Column('journal', sa.String(300), nullable=True),
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('added_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=_NOW, nullable=False),
    )
    op.create_index('ix_study_references_study_id', 'study_references', ['study_id'])
    op.create_table(
        'study_notes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('study_id', sa.Integer(), sa.ForeignKey('studies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('position', sa.Integer(), nullable=True),
        sa.Column('noted_on', sa.Date(), nullable=True),
        sa.Column('title', sa.String(200), nullable=True),
        sa.Column('text', sa.Text(), nullable=True),
        sa.Column('sample_id', sa.Integer(), sa.ForeignKey('samples.id', ondelete='SET NULL'), nullable=True),
        sa.Column('step_id', sa.Integer(), sa.ForeignKey('process_steps.id', ondelete='SET NULL'), nullable=True),
        sa.Column('analysis_id', sa.Integer(), sa.ForeignKey('analyses.id', ondelete='SET NULL'), nullable=True),
        sa.Column('author_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=_NOW, nullable=False),
    )
    op.create_index('ix_study_notes_study_id', 'study_notes', ['study_id'])


def downgrade() -> None:
    op.drop_table('study_notes')
    op.drop_table('study_references')
    op.drop_table('study_samples')
    op.drop_table('study_owners')
    op.drop_table('studies')
