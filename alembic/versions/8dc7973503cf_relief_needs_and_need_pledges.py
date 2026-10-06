"""relief needs and need pledges

Reshapes the unused scaffolding table zone_needs into the relief board's needs (a run, who posted it, how many are
PLEDGED, a status with goods-only items and check constraints so pledged can never exceed needed), and adds need_pledges
(a quantity and a time: no identity columns). A pledge is an unverified test entry; nothing here moves money or goods.

The table is empty and unused before this migration. If it has rows (someone used it), the migration refuses rather than
dropping them, both ways.

Revision ID: 8dc7973503cf
Revises: a28b563698ed
Create Date: 2026-10-06 02:58:21.040609

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '8dc7973503cf'
down_revision: Union[str, None] = 'a28b563698ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RELIEF_STATUS = ("open", "partial", "filled", "closed")
OLD_STATUS = ("open", "partially_fulfilled", "fulfilled")


def _refuse_if_rows(direction: str) -> None:
    n = op.get_bind().execute(sa.text("SELECT count(*) FROM zone_needs")).scalar()
    if n:
        raise RuntimeError(f"zone_needs has {n} rows: this migration {direction} would drop them. Remove them first.")


def upgrade() -> None:
    _refuse_if_rows("upgrade")
    relief_status = postgresql.ENUM(*RELIEF_STATUS, name="relief_status")
    relief_status.create(op.get_bind(), checkfirst=False)
    op.drop_column("zone_needs", "quantity_fulfilled")
    op.drop_column("zone_needs", "status")
    op.execute("DROP TYPE need_status")
    op.add_column("zone_needs", sa.Column("run_id", sa.UUID(), nullable=False))
    op.add_column("zone_needs", sa.Column("quantity_pledged", sa.Integer(), server_default="0", nullable=False))
    op.add_column("zone_needs", sa.Column("status", postgresql.ENUM(*RELIEF_STATUS, name="relief_status", create_type=False), nullable=False))
    op.add_column("zone_needs", sa.Column("created_by", sa.String(), nullable=False))
    op.add_column("zone_needs", sa.Column("is_synthetic", sa.Boolean(), server_default="false", nullable=False))
    op.create_index(op.f("ix_zone_needs_run_id"), "zone_needs", ["run_id"], unique=False)
    op.create_foreign_key("fk_zone_needs_run_id_runs", "zone_needs", "runs", ["run_id"], ["id"], ondelete="CASCADE")
    op.create_check_constraint("ck_zone_needs_needed_positive", "zone_needs", "quantity_needed > 0")
    op.create_check_constraint("ck_zone_needs_pledged_not_negative", "zone_needs", "quantity_pledged >= 0")
    op.create_check_constraint("ck_zone_needs_pledged_within_needed", "zone_needs", "quantity_pledged <= quantity_needed")
    op.create_check_constraint("ck_zone_needs_goods_only", "zone_needs", "item_type IN ('water', 'food', 'shelter', 'blankets', 'medical')")
    op.create_check_constraint("ck_zone_needs_filled_means_full", "zone_needs", "status <> 'filled' OR quantity_pledged = quantity_needed")
    op.create_table(
        "need_pledges",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("need_id", sa.UUID(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_need_pledges_quantity_positive"),
        sa.ForeignKeyConstraint(["need_id"], ["zone_needs.id"], name="fk_need_pledges_need_id_zone_needs", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_need_pledges_need_id"), "need_pledges", ["need_id"], unique=False)


def downgrade() -> None:
    _refuse_if_rows("downgrade")
    op.drop_index(op.f("ix_need_pledges_need_id"), table_name="need_pledges")
    op.drop_table("need_pledges")
    for name in ("ck_zone_needs_filled_means_full", "ck_zone_needs_goods_only", "ck_zone_needs_pledged_within_needed",
                 "ck_zone_needs_pledged_not_negative", "ck_zone_needs_needed_positive"):
        op.drop_constraint(name, "zone_needs", type_="check")
    op.drop_constraint("fk_zone_needs_run_id_runs", "zone_needs", type_="foreignkey")
    op.drop_index(op.f("ix_zone_needs_run_id"), table_name="zone_needs")
    for col in ("is_synthetic", "created_by", "status", "quantity_pledged", "run_id"):
        op.drop_column("zone_needs", col)
    op.execute("DROP TYPE relief_status")
    need_status = postgresql.ENUM(*OLD_STATUS, name="need_status")
    need_status.create(op.get_bind(), checkfirst=False)
    op.add_column("zone_needs", sa.Column("status", postgresql.ENUM(*OLD_STATUS, name="need_status", create_type=False), nullable=False))
    op.add_column("zone_needs", sa.Column("quantity_fulfilled", sa.Integer(), server_default="0", nullable=False))
    op.alter_column("zone_needs", "quantity_fulfilled", server_default=None)
