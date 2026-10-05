"""pledges

Revision ID: a28b563698ed
Revises: 7e7b75c5ae11
Create Date: 2026-10-05 14:59:27.610954

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a28b563698ed'
down_revision: Union[str, None] = '7e7b75c5ae11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('pledges',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('zone_id', sa.UUID(), nullable=False),
    # item_type already exists (the initial schema's zone_needs): reuse it, never recreate it
    sa.Column('item_type', postgresql.ENUM('blankets', 'food', 'water', 'medical', 'shelter', 'boat', 'vehicle', 'other', name='item_type', create_type=False), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('donor', sa.String(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('offered_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('closed_kind', sa.Enum('received', 'withdrawn', name='pledge_close_kind'), nullable=True),
    sa.Column('closed_by', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name='fk_pledges_run_id_runs', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['zone_id'], ['zones.id'], name='fk_pledges_zone_id_zones', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_pledges_run_zone', 'pledges', ['run_id', 'zone_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_pledges_run_zone', table_name='pledges')
    op.drop_table('pledges')
    op.execute('DROP TYPE pledge_close_kind')  # created with the table; item_type belongs to zone_needs and stays
