"""case source

Revision ID: 9b2120d07c3e
Revises: a4c1e7f2b9d3
Create Date: 2026-09-30 13:33:56.742572

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2


# revision identifiers, used by Alembic.
revision: str = '9b2120d07c3e'
down_revision: Union[str, None] = 'a4c1e7f2b9d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cases', sa.Column('source', sa.String(), nullable=True))
    op.create_index(op.f('ix_cases_source'), 'cases', ['source'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_cases_source'), table_name='cases')
    op.drop_column('cases', 'source')
