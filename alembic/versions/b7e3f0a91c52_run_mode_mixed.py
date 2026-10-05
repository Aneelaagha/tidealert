"""run mode mixed

RunMode.mixed: a run that combines a real recorded event with a synthetic layer (e.g. Harvey's real flood and
isolation results with synthetic responders and assignments). Registered explicitly, never inferred, so its badge
and caveat follow it everywhere.

Downgrade recreates the enum without the value (Postgres can't drop an enum value in place) and refuses while any
run still has mode "mixed", rather than silently rewriting or deleting it.

Revision ID: b7e3f0a91c52
Revises: edb82fd12167
Create Date: 2026-10-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7e3f0a91c52'
down_revision: Union[str, None] = 'edb82fd12167'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE run_mode ADD VALUE IF NOT EXISTS 'mixed'")


def downgrade() -> None:
    mixed = op.get_bind().execute(sa.text("SELECT count(*) FROM runs WHERE mode::text = 'mixed'")).scalar()
    if mixed:
        raise RuntimeError(f"{mixed} run(s) have mode 'mixed': delete them (or re-register them) before downgrading")
    op.execute("ALTER TYPE run_mode RENAME TO run_mode_old")
    op.execute("CREATE TYPE run_mode AS ENUM ('replay', 'scenario', 'live')")
    op.execute("ALTER TABLE runs ALTER COLUMN mode TYPE run_mode USING mode::text::run_mode")
    op.execute("DROP TYPE run_mode_old")
