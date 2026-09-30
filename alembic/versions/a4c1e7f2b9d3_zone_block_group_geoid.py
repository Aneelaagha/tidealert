"""zone block group geoid

Revision ID: a4c1e7f2b9d3
Revises: 6e3e632e2391
Create Date: 2026-09-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4c1e7f2b9d3'
down_revision: Union[str, None] = '6e3e632e2391'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('zones', sa.Column('block_group_geoid', sa.String(), nullable=True))
    op.create_index(op.f('ix_zones_block_group_geoid'), 'zones', ['block_group_geoid'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_zones_block_group_geoid'), table_name='zones')
    op.drop_column('zones', 'block_group_geoid')
