"""contribution direction and observation time

Revision ID: 91969f7bd80d
Revises: 140851eab8b5
Create Date: 2026-09-30 14:55:43.867967

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2


# revision identifiers, used by Alembic.
revision: str = '91969f7bd80d'
down_revision: Union[str, None] = '140851eab8b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DIRECTION = sa.Enum('supports', 'contradicts', 'neutral', 'procedural', name='contribution_direction')


def upgrade() -> None:
    DIRECTION.create(op.get_bind(), checkfirst=True)
    op.add_column('case_engine_contributions',
                  sa.Column('direction', DIRECTION, server_default='supports', nullable=False))
    op.add_column('case_engine_contributions', sa.Column('observed_at', sa.DateTime(timezone=True), nullable=True))
    # Existing contributions: best available observation time is their case's opening time.
    op.execute("UPDATE case_engine_contributions e SET observed_at = c.opened_at FROM cases c WHERE c.id = e.case_id")
    op.alter_column('case_engine_contributions', 'observed_at', nullable=False, server_default=sa.text('now()'))
    op.add_column('case_engine_contributions',
                  sa.Column('independent_sources', sa.Integer(), server_default='1', nullable=False))


def downgrade() -> None:
    op.drop_column('case_engine_contributions', 'independent_sources')
    op.drop_column('case_engine_contributions', 'observed_at')
    op.drop_column('case_engine_contributions', 'direction')
    DIRECTION.drop(op.get_bind(), checkfirst=True)
