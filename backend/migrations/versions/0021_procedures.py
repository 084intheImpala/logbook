"""Procedures: how someone does a technique, and which one an entry followed

Revision ID: 0021
Revises: 0020

New tables procedures (title, the step or analysis type it is for, summary,
the procedure itself in Markdown, visibility) and procedure_owners (its co-owners).
Process steps and analyses get `procedure_id`: the procedure followed.
"""
from alembic import op
import sqlalchemy as sa

revision = '0021'
down_revision = '0020'
branch_labels = None
depends_on = None

_NOW = sa.text('(CURRENT_TIMESTAMP)')


def upgrade() -> None:
    op.create_table(
        'procedures',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('step_type_id', sa.Integer(), sa.ForeignKey('process_step_types.id', ondelete='SET NULL'), nullable=True),
        sa.Column('analysis_type_id', sa.Integer(), sa.ForeignKey('analysis_types.id', ondelete='SET NULL'), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('text', sa.Text(), nullable=True),
        sa.Column('visibility', sa.String(10), server_default='team', nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=_NOW, nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=_NOW, nullable=True),
    )
    op.create_index('ix_procedures_step_type_id', 'procedures', ['step_type_id'])
    op.create_index('ix_procedures_analysis_type_id', 'procedures', ['analysis_type_id'])
    op.create_table(
        'procedure_owners',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('procedure_id', sa.Integer(), sa.ForeignKey('procedures.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.UniqueConstraint('procedure_id', 'user_id'),
    )
    op.create_index('ix_procedure_owners_procedure_id', 'procedure_owners', ['procedure_id'])
    op.create_index('ix_procedure_owners_user_id', 'procedure_owners', ['user_id'])
    for table in ('process_steps', 'analyses'):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column('procedure_id', sa.Integer(), nullable=True))
            batch.create_index(f'ix_{table}_procedure_id', ['procedure_id'])
            batch.create_foreign_key(f'fk_{table}_procedure_id', 'procedures', ['procedure_id'], ['id'],
                                     ondelete='SET NULL')


def downgrade() -> None:
    for table in ('process_steps', 'analyses'):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f'fk_{table}_procedure_id', type_='foreignkey')
            batch.drop_index(f'ix_{table}_procedure_id')
            batch.drop_column('procedure_id')
    op.drop_table('procedure_owners')
    op.drop_table('procedures')
