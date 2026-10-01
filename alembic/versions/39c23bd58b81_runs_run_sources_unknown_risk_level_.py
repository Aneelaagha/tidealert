"""runs, run sources, unknown risk level, nullable data confidence

Revision ID: 39c23bd58b81
Revises: 91969f7bd80d
Create Date: 2026-09-30 15:26:17.587833

- runs (with an explicit run_mode: replay / scenario / live) and run_sources
  (the data sources a run actually reads; many-to-many, with an optional
  per-run staleness override).
- cases.run_id, backfilled for the runs that exist today. The backfill only
  recognises those runs, listed below with their mode set explicitly; any
  other case source stops the migration instead of guessing a mode.
- risk_level gains 'unknown', now the default; every 'safe' row is a
  default nobody asserted (only the listening engine writes risk_level, and
  it only raises it), so all become 'unknown'.
- zones.data_confidence becomes nullable; the never-written 0s become null.
"""
from datetime import datetime, timezone
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import geoalchemy2


# revision identifiers, used by Alembic.
revision: str = '39c23bd58b81'
down_revision: Union[str, None] = '91969f7bd80d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


RUN_MODE = postgresql.ENUM('replay', 'scenario', 'live', name='run_mode', create_type=False)
UTC = timezone.utc

# The runs that exist today. Sources: what each run actually reads. The Harvey isolation replay reads only the
# USGS gauge records (stage and discharge); rain (AORC) and NWM are not inputs to it. The silence scenario reads
# check-in probe responses, which are not recorded as signals of any data source, so it links none.
KNOWN_RUNS = [
    dict(name='backtest:2017-08-25..2017-09-02', case_source_like='backtest:2017-08-25..2017-09-02:USGS-%',
         mode='replay', window=(datetime(2017, 8, 25, 5, tzinfo=UTC), datetime(2017, 9, 3, 5, tzinfo=UTC)),
         description='Hurricane Harvey 2017: isolation replayed from USGS gauge records (White Oak, Greens, Hunting)',
         sources=['USGS 08074500 continuous', 'USGS 08075770 continuous', 'USGS 08076000 continuous']),
    dict(name='backtest:2026-09-02..2026-09-02:synthetic:silence-baseline',
         case_source_like='backtest:2026-09-02..2026-09-02:synthetic:silence-baseline',
         mode='scenario', window=(datetime(2026, 9, 2, 14, tzinfo=UTC), datetime(2026, 9, 2, 19, tzinfo=UTC)),
         description='Synthetic households: silence baseline test', sources=[]),
    dict(name='replay:2026-09-10T14:00..17:00Z:synthetic:listening',
         case_source_like='replay:2026-09-10T14:00..17:00Z:synthetic:listening',
         mode='scenario', window=(datetime(2026, 9, 10, 14, tzinfo=UTC), datetime(2026, 9, 10, 17, tzinfo=UTC)),
         description='Synthetic households: listening engine scenario', sources=['Listening: household replies']),
]


def upgrade() -> None:
    # A new enum value must be committed before it can be used, so it is added first, on its own (idempotent);
    # everything after runs in one transaction.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE risk_level ADD VALUE IF NOT EXISTS 'unknown' BEFORE 'safe'")
    bind = op.get_bind()

    # ---- runs and run_sources
    RUN_MODE.create(bind, checkfirst=True)
    op.create_table(
        'runs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('mode', RUN_MODE, nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('window_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name='runs_pkey'),
        sa.UniqueConstraint('name', name='runs_name_key'),
    )
    op.create_table(
        'run_sources',
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.Column('data_source_id', sa.UUID(), nullable=False),
        sa.Column('stale_after_override_seconds', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name='fk_run_sources_run_id_runs', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['data_source_id'], ['data_sources.id'],
                                name='fk_run_sources_data_source_id_data_sources', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('run_id', 'data_source_id', name='run_sources_pkey'),
    )

    # ---- cases.run_id, backfilled from the known runs
    op.add_column('cases', sa.Column('run_id', sa.UUID(), nullable=True))
    now = datetime.now(UTC)
    for run in KNOWN_RUNS:
        n = bind.execute(sa.text('SELECT count(*) FROM cases WHERE source LIKE :p'),
                         {'p': run['case_source_like']}).scalar()
        if not n:
            continue
        run_id = uuid.uuid4()
        bind.execute(sa.text(
            'INSERT INTO runs (id, name, mode, description, window_start, window_end, created_at) '
            'VALUES (:id, :name, CAST(:mode AS run_mode), :d, :s, :e, :now)'),
            dict(id=run_id, name=run['name'], mode=run['mode'], d=run['description'],
                 s=run['window'][0], e=run['window'][1], now=now))
        for source in run['sources']:
            bind.execute(sa.text(
                'INSERT INTO run_sources (run_id, data_source_id) SELECT :r, id FROM data_sources WHERE name = :n'),
                dict(r=run_id, n=source))
        bind.execute(sa.text('UPDATE cases SET run_id = :r WHERE source LIKE :p'),
                     dict(r=run_id, p=run['case_source_like']))
    unmatched = bind.execute(sa.text(
        'SELECT coalesce(source, \'<null>\'), count(*) FROM cases WHERE run_id IS NULL GROUP BY 1')).all()
    if unmatched:
        raise RuntimeError('Cases whose run (and so mode) this migration does not know; register them explicitly: '
                           + ', '.join(f'{s} ({n})' for s, n in unmatched))
    op.alter_column('cases', 'run_id', nullable=False)
    op.create_foreign_key('fk_cases_run_id_runs', 'cases', 'runs', ['run_id'], ['id'])
    op.create_index(op.f('ix_cases_run_id'), 'cases', ['run_id'], unique=False)

    # ---- risk_level 'unknown'
    op.execute("UPDATE zones SET risk_level = 'unknown' WHERE risk_level = 'safe'")
    op.alter_column('zones', 'risk_level', server_default='unknown')

    # ---- data_confidence nullable; nothing has ever computed it
    op.alter_column('zones', 'data_confidence', existing_type=sa.Integer(), nullable=True)
    op.execute('UPDATE zones SET data_confidence = NULL WHERE data_confidence = 0')


def downgrade() -> None:
    op.execute('UPDATE zones SET data_confidence = 0 WHERE data_confidence IS NULL')
    op.alter_column('zones', 'data_confidence', existing_type=sa.Integer(), nullable=False)

    # Postgres cannot drop an enum value: rebuild the type without 'unknown'.
    op.alter_column('zones', 'risk_level', server_default=None)
    op.execute("UPDATE zones SET risk_level = 'safe' WHERE risk_level = 'unknown'")
    op.execute('ALTER TYPE risk_level RENAME TO risk_level_old')
    op.execute("CREATE TYPE risk_level AS ENUM ('safe', 'elevated', 'extreme')")
    op.execute('ALTER TABLE zones ALTER COLUMN risk_level TYPE risk_level USING risk_level::text::risk_level')
    op.execute('DROP TYPE risk_level_old')

    op.drop_index(op.f('ix_cases_run_id'), table_name='cases')
    op.drop_constraint('fk_cases_run_id_runs', 'cases', type_='foreignkey')
    op.drop_column('cases', 'run_id')
    op.drop_table('run_sources')
    op.drop_table('runs')
    RUN_MODE.drop(op.get_bind(), checkfirst=True)
