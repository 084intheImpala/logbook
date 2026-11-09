"""Where a deposited layer goes: on top of which layer, and whether it covers all of it

Revision ID: 0018
Revises: 0017

Process steps get `on_step_id` (the Deposition whose layer this one is
deposited on; none: on everything so far), `on_substrate` (on the bare
substrate) and `partial` (covers only part of it, e.g. contacts through a
mask). Existing depositions keep covering the whole stack.
"""
from alembic import op
import sqlalchemy as sa

revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("process_steps") as batch:
        batch.add_column(sa.Column("on_step_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("on_substrate", sa.Boolean(), server_default=sa.false(), nullable=False))
        batch.add_column(sa.Column("partial", sa.Boolean(), server_default=sa.false(), nullable=False))
        batch.create_foreign_key("fk_process_steps_on_step_id", "process_steps", ["on_step_id"], ["id"],
                                 ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("process_steps") as batch:
        batch.drop_constraint("fk_process_steps_on_step_id", type_="foreignkey")
        batch.drop_column("partial")
        batch.drop_column("on_substrate")
        batch.drop_column("on_step_id")
