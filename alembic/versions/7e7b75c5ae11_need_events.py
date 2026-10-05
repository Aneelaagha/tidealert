"""need events

Revision ID: 7e7b75c5ae11
Revises: b7e3f0a91c52
Create Date: 2026-10-05 14:44:32.321193

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '7e7b75c5ae11'
down_revision: Union[str, None] = 'b7e3f0a91c52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('need_events',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('zone_id', sa.UUID(), nullable=False),
    # item_type already exists (the initial schema's zone_needs): reuse it, never recreate it
    sa.Column('item_type', postgresql.ENUM('blankets', 'food', 'water', 'medical', 'shelter', 'boat', 'vehicle', 'other', name='item_type', create_type=False), nullable=False),
    sa.Column('event', sa.Enum('requested', 'fulfilled', 'withdrawn', name='need_event_kind'), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('actor', sa.String(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name='fk_need_events_run_id_runs', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['zone_id'], ['zones.id'], name='fk_need_events_zone_id_zones', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_need_events_run_zone_at', 'need_events', ['run_id', 'zone_id', 'at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_need_events_run_zone_at', table_name='need_events')
    op.drop_table('need_events')
    op.execute('DROP TYPE need_event_kind')  # created with the table; item_type belongs to zone_needs and stays
