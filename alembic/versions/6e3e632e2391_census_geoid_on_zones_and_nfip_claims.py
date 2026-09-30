"""census geoid on zones and nfip claims

Revision ID: 6e3e632e2391
Revises: 110369599447
Create Date: 2026-09-30 01:21:41.511344

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2


# revision identifiers, used by Alembic.
revision: str = '6e3e632e2391'
down_revision: Union[str, None] = '110369599447'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('nfip_claims', sa.Column('census_geoid', sa.String(), nullable=True))
    op.create_index(op.f('ix_nfip_claims_census_geoid'), 'nfip_claims', ['census_geoid'], unique=False)
    op.add_column('zones', sa.Column('census_geoid', sa.String(), nullable=True))
    op.create_unique_constraint('uq_zones_census_geoid', 'zones', ['census_geoid'])


def downgrade() -> None:
    op.drop_constraint('uq_zones_census_geoid', 'zones', type_='unique')
    op.drop_column('zones', 'census_geoid')
    op.drop_index(op.f('ix_nfip_claims_census_geoid'), table_name='nfip_claims')
    op.drop_column('nfip_claims', 'census_geoid')
