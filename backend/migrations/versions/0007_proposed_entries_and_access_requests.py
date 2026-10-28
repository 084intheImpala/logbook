"""proposed entries and access requests

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('access_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('sample_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('level', sa.String(length=10), nullable=False),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('decided_by_id', sa.Integer(), nullable=True),
    sa.Column('decided_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['decided_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['sample_id'], ['samples.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_access_requests_sample_id'), 'access_requests', ['sample_id'], unique=False)
    op.create_index(op.f('ix_access_requests_user_id'), 'access_requests', ['user_id'], unique=False)
    for table in ('analyses', 'process_steps'):
        # batch mode so the foreign key can also be added on SQLite (the tests)
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column('status', sa.String(length=10), server_default='approved', nullable=False))
            batch.add_column(sa.Column('proposed_by_id', sa.Integer(), nullable=True))
            batch.add_column(sa.Column('proposed_at', sa.DateTime(), nullable=True))
            batch.create_index(f'ix_{table}_proposed_by_id', ['proposed_by_id'], unique=False)
            batch.create_foreign_key(f'fk_{table}_proposed_by_id_users', 'users', ['proposed_by_id'], ['id'],
                                     ondelete='SET NULL')


def downgrade() -> None:
    for table in ('process_steps', 'analyses'):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f'fk_{table}_proposed_by_id_users', type_='foreignkey')
            batch.drop_index(f'ix_{table}_proposed_by_id')
            batch.drop_column('proposed_at')
            batch.drop_column('proposed_by_id')
            batch.drop_column('status')
    op.drop_index(op.f('ix_access_requests_user_id'), table_name='access_requests')
    op.drop_index(op.f('ix_access_requests_sample_id'), table_name='access_requests')
    op.drop_table('access_requests')
