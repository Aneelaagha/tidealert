"""Relief needs and pledges: coordinators post what a zone needs, anyone can PLEDGE a quantity against it, and the board
ranks the needs by the zone's real isolation state. Everything here is a pledge, an unverified test entry:

- nothing moves money or goods, and nothing tracks a delivery: a pledge is never "delivered" or "received";
- no payments, no money item, no donor identity (a pledge stores a quantity and a time, nothing about who made it);
- no authentication: `created_by` is free text, so anyone who can reach the API can post a need or pledge;
- replay runs refuse needs and pledges, as task actions do: they would invent a relief history for a real event (422).

The zone's access state comes from the safety service (app.services.safety) at the slider time, so a need in a cut-off
zone ranks above one in a zone with a dry route, and a zone whose access was not assessed is ranked as "not assessed",
never as lower need than a dry one. The needs and pledges themselves have no history (a current-state board): moving the
slider re-reads each zone's access, not the board's contents.

Pledges lock the need row (SELECT ... FOR UPDATE, after flushing pending changes, as app.services.task_actions does since
PR #18) so concurrent pledges can't both take the last unit; the database also refuses pledged > needed.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NeedPledge, Run, Zone, ZoneNeed
from app.models.run import RunMode
from app.models.zone_need import RELIEF_ITEMS, ItemType, ReliefStatus
from app.services import map_state, run_events, safety

LABEL = "Test pledges. No payment is processed."
MAX_QUANTITY = 1_000_000
REPLAY_REASON = ("Needs and pledges are off for replays because they would invent a relief history for a real event. "
                 "Use the mixed scenario.")
# item -> (name, unit). The units are how the board counts; they are not measured needs.
ITEMS = {"water": ("Water", "litres"), "food": ("Food rations", "rations"), "shelter": ("Shelter kits", "kits"),
         "blankets": ("Blankets", "blankets"), "medical": ("Medical kits", "kits")}
ACCESS_LABEL = {"isolated": "Cut off", "possibly_isolated": "May be cut off", "not_evaluated": "Not assessed",
                "reconnected": "Reconnected, not a guarantee", "reachable": "Dry route"}
# Most urgent first: cut off, may be cut off, not assessed (never below a dry zone), reconnected, dry route.
ACCESS_ORDER = {"isolated": 0, "possibly_isolated": 1, "not_evaluated": 2, "reconnected": 3, "reachable": 4}
SEED_BY = "script:mixed-scenario (synthetic)"
SEED_ITEMS = ("water", "food", "medical")  # the three seeded needs, in this order, largest-population zone first


class ReliefError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


def writable_reason(run: Run) -> Optional[str]:
    return REPLAY_REASON if run.mode == RunMode.replay else None


def _view(n: ZoneNeed, zone_name: str, access: Optional[dict]) -> dict:
    a = access or {"zone_access": "not_evaluated", "since": None, "reason": "access not read"}
    open_q = n.quantity_needed - n.quantity_pledged
    return {
        "id": str(n.id), "run_id": str(n.run_id), "zone_id": str(n.zone_id), "zone_name": zone_name,
        "item_type": n.item_type.value, "item_label": ITEMS[n.item_type.value][0], "unit": ITEMS[n.item_type.value][1],
        "quantity_needed": n.quantity_needed, "quantity_pledged": n.quantity_pledged, "quantity_open": open_q,
        "percent": round(100 * n.quantity_pledged / n.quantity_needed, 1), "status": n.status.value,
        "created_by": n.created_by, "is_synthetic": n.is_synthetic, "created_at": n.created_at.isoformat(),
        "access": {"state": a["zone_access"], "label": ACCESS_LABEL[a["zone_access"]], "since": a["since"].isoformat() if a.get("since") else None},
    }


def _rank(v: dict):
    # access urgency, then the largest open quantity, then a fixed tie-break so the order is deterministic
    return (ACCESS_ORDER[v["access"]["state"]], -v["quantity_open"], v["created_at"], v["id"])


def board(db: Session, run: Run, at: datetime) -> dict:
    rows = list(db.execute(select(ZoneNeed, Zone.name).join(Zone, Zone.id == ZoneNeed.zone_id).where(ZoneNeed.run_id == run.id)))
    access = safety.zone_access(db, run, at, {n.zone_id for n, _ in rows}) if rows else {}
    needs = sorted((_view(n, name, access.get(str(n.zone_id))) for n, name in rows), key=_rank)
    reason = writable_reason(run)
    return {"run_id": str(run.id), "mode": run.mode.value, "at": at.isoformat(), "label": LABEL, "writable": reason is None,
            "blocked_reason": reason, "items": {k: {"label": v[0], "unit": v[1]} for k, v in ITEMS.items()},
            "access_labels": ACCESS_LABEL, "needs": needs}


def one(db: Session, need: ZoneNeed, at: datetime) -> dict:
    zone = db.get(Zone, need.zone_id)
    access = safety.zone_access(db, db.get(Run, need.run_id), at, {need.zone_id})
    return _view(need, zone.name, access.get(str(need.zone_id)))


def _lock(db: Session, row) -> None:
    """Re-read `row` with SELECT ... FOR UPDATE: it waits for any other transaction holding it, then sees its committed
    state. Flush first: a refresh discards unflushed changes (the lesson of PR #18)."""
    db.flush()
    db.refresh(row, with_for_update=True)


def post_need(db: Session, run: Run, zone_id, item_type: str, quantity: int, created_by: str, is_synthetic: bool = False) -> ZoneNeed:
    reason = writable_reason(run)
    if reason:
        raise ReliefError(422, reason)
    if item_type not in RELIEF_ITEMS:
        raise ReliefError(422, f"item must be one of: {', '.join(ITEMS[i][0] for i in RELIEF_ITEMS)} (goods only)")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or not 0 < quantity <= MAX_QUANTITY:
        raise ReliefError(422, f"quantity needed must be a whole number from 1 to {MAX_QUANTITY:,}")
    created_by = (created_by or "").strip()
    if not created_by:
        raise ReliefError(422, "created_by is required (who is posting this; there is no authentication yet)")
    zone = db.get(Zone, zone_id)
    if zone is None:
        raise ReliefError(404, "zone not found")
    if zone.region not in map_state.run_regions(db, run):
        raise ReliefError(422, "this zone is not part of the run's view")
    need = ZoneNeed(run_id=run.id, zone_id=zone.id, item_type=ItemType(item_type), quantity_needed=quantity, quantity_pledged=0,
                    status=ReliefStatus.open, created_by=created_by, is_synthetic=is_synthetic)
    db.add(need)
    db.flush()
    return need


def _get(db: Session, need_id) -> ZoneNeed:
    need = db.get(ZoneNeed, need_id)
    if need is None:
        raise ReliefError(404, "need not found")
    return need


def pledge(db: Session, need_id, quantity: int) -> ZoneNeed:
    """Pledge `quantity` against a need. The need row is locked, so exactly the open quantity can be pledged, however many
    pledges arrive at once. Refused with a 409 that states the open quantity when it would exceed it."""
    need = _get(db, need_id)
    run = db.get(Run, need.run_id)
    reason = writable_reason(run)
    if reason:
        raise ReliefError(422, reason)
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise ReliefError(422, "quantity must be a whole number of 1 or more")
    _lock(db, need)
    if need.status == ReliefStatus.closed:
        raise ReliefError(409, "this need is closed: no more can be pledged")
    open_q = need.quantity_needed - need.quantity_pledged
    if open_q == 0:
        raise ReliefError(409, "this need is filled: 0 are still open")
    if quantity > open_q:
        raise ReliefError(409, f"only {open_q:,} {ITEMS[need.item_type.value][1]} are still open; cannot pledge {quantity:,}")
    db.add(NeedPledge(need_id=need.id, quantity=quantity))
    need.quantity_pledged += quantity
    need.status = ReliefStatus.filled if need.quantity_pledged == need.quantity_needed else ReliefStatus.partial
    db.flush()
    return need


def close_need(db: Session, need_id) -> ZoneNeed:
    need = _get(db, need_id)
    reason = writable_reason(db.get(Run, need.run_id))
    if reason:
        raise ReliefError(422, reason)
    _lock(db, need)
    if need.status == ReliefStatus.closed:
        raise ReliefError(409, "this need is already closed")
    need.status = ReliefStatus.closed
    db.flush()
    return need


def seed_mixed(db: Session, run: Run) -> list[ZoneNeed]:
    """The demo's three synthetic needs on the mixed run, by a fixed rule (idempotent: a rerun replaces them).

    Rule: at the event's recorded peak (app.services.run_events.run_peak), take the zones the isolation engine finds CUT OFF
    among the run's flagged zones; order them by recorded population, largest first, ties by zone id; the first three get
    water, food rations and medical kits in that order, each needing one unit per recorded resident. The quantity is a
    placeholder ratio for the demo, not a measured need. They are flagged is_synthetic and created by SEED_BY."""
    peak = run_events.run_peak(run)
    if run.mode != RunMode.mixed or peak is None:
        raise ReliefError(422, "seeding is defined for the mixed Harvey run only")
    for old in db.scalars(select(ZoneNeed).where(ZoneNeed.run_id == run.id, ZoneNeed.is_synthetic.is_(True), ZoneNeed.created_by == SEED_BY)):
        db.delete(old)
    db.flush()
    zones = {z.id: z for z in db.scalars(select(Zone).where(Zone.region.in_(map_state.run_regions(db, run))))}
    access = safety.zone_access(db, run, peak, set(zones))
    cut = [z for zid, z in zones.items() if access[str(zid)]["zone_access"] == "isolated" and (z.population_count or 0) > 0]
    cut.sort(key=lambda z: (-(z.population_count or 0), str(z.id)))
    made = []
    for zone, item in zip(cut, SEED_ITEMS):
        made.append(post_need(db, run, zone.id, item, zone.population_count, SEED_BY, is_synthetic=True))
    return made
