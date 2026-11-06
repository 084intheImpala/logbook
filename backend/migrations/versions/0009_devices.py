"""devices on a sample

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('devices',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('sample_id', sa.Integer(), nullable=False),
    sa.Column('label', sa.String(length=50), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('made_step_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['sample_id'], ['samples.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['made_step_id'], ['process_steps.id'], ondelete='SET NULL', name='fk_devices_made_step_id'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('sample_id', 'label')
    )
    op.create_index(op.f('ix_devices_sample_id'), 'devices', ['sample_id'], unique=False)
    op.create_index(op.f('ix_devices_made_step_id'), 'devices', ['made_step_id'], unique=False)
    with op.batch_alter_table('analyses') as batch:
        batch.add_column(sa.Column('device_id', sa.Integer(), nullable=True))
        batch.create_index(batch.f('ix_analyses_device_id'), ['device_id'], unique=False)
        batch.create_foreign_key('fk_analyses_device_id', 'devices', ['device_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    with op.batch_alter_table('analyses') as batch:
        batch.drop_constraint('fk_analyses_device_id', type_='foreignkey')
        batch.drop_index(batch.f('ix_analyses_device_id'))
        batch.drop_column('device_id')
    op.drop_index(op.f('ix_devices_made_step_id'), table_name='devices')
    op.drop_index(op.f('ix_devices_sample_id'), table_name='devices')
    op.drop_table('devices')
