"""probe cascade

Revision ID: 140851eab8b5
Revises: 9b2120d07c3e
Create Date: 2026-09-30 14:31:52.646824

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2


# revision identifiers, used by Alembic.
revision: str = '140851eab8b5'
down_revision: Union[str, None] = '9b2120d07c3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PROBE_PURPOSE = sa.Enum('checkin', 'depth_followup', 'neighbor_prompt', name='probe_purpose')


def upgrade() -> None:
    PROBE_PURPOSE.create(op.get_bind(), checkfirst=True)
    op.add_column('probe_responses', sa.Column('parent_probe_id', sa.UUID(), nullable=True))
    op.add_column('probe_responses', sa.Column('purpose', PROBE_PURPOSE, nullable=True))
    op.create_index(op.f('ix_probe_responses_parent_probe_id'), 'probe_responses', ['parent_probe_id'], unique=False)
    op.create_foreign_key('fk_probe_responses_parent_probe_id', 'probe_responses', 'probe_responses',
                          ['parent_probe_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_probe_responses_parent_probe_id', 'probe_responses', type_='foreignkey')
    op.drop_index(op.f('ix_probe_responses_parent_probe_id'), table_name='probe_responses')
    op.drop_column('probe_responses', 'purpose')
    op.drop_column('probe_responses', 'parent_probe_id')
    PROBE_PURPOSE.drop(op.get_bind(), checkfirst=True)
