"""The needs board: what an OPERATOR says each zone of a run needs, as of a time. Entered by a person, never
measured or inferred, and labelled so everywhere. Nothing here matches, routes or allocates anything.

- Append-only events (app.models.need_event): requested, fulfilled, withdrawn. A zone's open need for an item at
  `at` is requested - fulfilled - withdrawn, summed over the events up to `at`; a past time reads only what had been
  entered by then.
- Keyed by run. The Harvey replay and the mixed run share zones, so a need entered on the mixed run does not
  appear on the replay.
- Replay runs are read-only, as for task actions: entered needs would be typed-in claims added to a record of a
  real event (422). Mixed, scenario and live runs accept entries.
- Like task actions: `actor` is required (free text; there is no authentication yet), an event happens at a time on
  the run's clock (default: the end of the window, now if live), not earlier than the item's latest event in that
  zone, and rows are locked so concurrent entries can't both spend the same remaining quantity.
- Each open need is read with its zone's access from the isolation engine's stored output (app.services.safety),
  so the board can say which needs are in a cut-off zone.
"""
from collections import defaultdict
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NeedEvent, Run, Zone
from app.models.need_event import NeedEventKind
from app.models.run import RunMode
from app.models.zone_need import ItemType
from app.services import map_state, safety

MAX_QUANTITY = 1_000_000
MAX_NOTE = 300
LABEL = "Entered by an operator at the slider time. Not measured, and not checked against any other source."


class NeedError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


def read_only_reason(run: Run) -> Optional[str]:
    """Why people can't enter needs on this run, or None if they can. /needs reports it so the page can say why."""
    if run.mode == RunMode.replay:
        return (f"run {run.name!r} is a replay of a recorded event: needs entered here would be typed-in claims "
                "added to a record of a real event. Use the mixed run or a scenario")
    return None


def _event(e: NeedEvent) -> dict:
    return {"id": str(e.id), "at": e.at.isoformat(), "item_type": e.item_type.value, "event": e.event.value,
            "quantity": e.quantity, "actor": e.actor, "note": e.note or ""}


def _fold(events: list[NeedEvent]) -> list[dict]:
    """Per item: totals and what is still open, from events oldest first."""
    items: dict[str, dict] = {}
    for e in events:
        i = items.setdefault(e.item_type.value, {"item_type": e.item_type.value, "requested": 0, "fulfilled": 0,
                                                 "withdrawn": 0})
        i[e.event.value] += e.quantity
    for i in items.values():
        i["remaining"] = i["requested"] - i["fulfilled"] - i["withdrawn"]
    return sorted(items.values(), key=lambda i: i["item_type"])


def record(db: Session, run: Run, zone_id, item_type: ItemType, event: NeedEventKind, quantity: int, actor: str,
           at: Optional[datetime] = None, note: str = "") -> NeedEvent:
    reason = read_only_reason(run)
    if reason:
        raise NeedError(422, reason)
    actor = (actor or "").strip()
    if not actor:
        raise NeedError(422, "actor is required (who is entering this; there is no authentication yet)")
    if not 0 < quantity <= MAX_QUANTITY:
        raise NeedError(422, f"quantity must be a whole number from 1 to {MAX_QUANTITY:,}")
    note = (note or "").strip()
    if len(note) > MAX_NOTE:
        raise NeedError(422, f"note is limited to {MAX_NOTE} characters (and must hold no personal details)")
    zone = db.get(Zone, zone_id)
    if zone is None:
        raise NeedError(404, "zone not found")
    if zone.region not in map_state.run_regions(db, run):
        raise NeedError(422, "this zone is not part of the run's view")
    try:
        when = map_state.resolve_at(run, at)
    except map_state.TimeOutOfWindow as exc:
        raise NeedError(422, str(exc))
    db.flush()
    db.refresh(zone, with_for_update=True)  # one writer per zone at a time: the checks below read what it wrote
    prior = list(db.scalars(select(NeedEvent).where(NeedEvent.run_id == run.id, NeedEvent.zone_id == zone.id,
                                                    NeedEvent.item_type == item_type).order_by(NeedEvent.at,
                                                                                                NeedEvent.created_at)))
    if prior and when < prior[-1].at:
        raise NeedError(422, f"at {when.isoformat()} is before this item's latest entry in the zone "
                             f"({prior[-1].at.isoformat()})")
    remaining = _fold(prior)[0]["remaining"] if prior else 0
    if event != NeedEventKind.requested and quantity > remaining:
        raise NeedError(409, f"only {remaining} of {item_type.value} is still open in this zone; cannot "
                             f"{event.value.removesuffix('ed') if event == NeedEventKind.fulfilled else 'withdraw'} {quantity}")
    row = NeedEvent(run_id=run.id, zone_id=zone.id, item_type=item_type, event=event, quantity=quantity,
                    actor=actor, at=when, note=note or None)
    db.add(row)
    db.flush()
    return row


def zone_state(db: Session, run: Run, zone_id, at: datetime) -> dict:
    """One zone's items and entries as of `at` (the response to an entry)."""
    return needs_as_of(db, run, at, [zone_id])["zones"].get(str(zone_id), {"items": [], "events": [], "open": 0})


def needs_as_of(db: Session, run: Run, at: datetime, only_zones=None) -> dict:
    q = select(NeedEvent).where(NeedEvent.run_id == run.id, NeedEvent.at <= at).order_by(NeedEvent.at,
                                                                                         NeedEvent.created_at)
    if only_zones is not None:
        q = q.where(NeedEvent.zone_id.in_(only_zones))
    by_zone: dict[str, list[NeedEvent]] = defaultdict(list)
    for e in db.scalars(q):
        by_zone[str(e.zone_id)].append(e)
    zones = {}
    for zid, events in by_zone.items():
        items = _fold(events)
        zones[zid] = {"items": items, "events": [_event(e) for e in events],
                      "open": sum(i["remaining"] for i in items)}
    names = {str(z.id): z for z in db.scalars(select(Zone).where(Zone.id.in_(list(zones))))} if zones else {}
    open_zones = [z for z, v in zones.items() if v["open"] > 0]
    access = safety.zone_access(db, run, at, open_zones) if open_zones else {}
    for zid, v in zones.items():
        z = names.get(zid)
        v["name"], v["population"] = (z.name, z.population_count) if z else (None, None)
        a = access.get(zid)
        v["zone_access"] = a["zone_access"] if a and v["open"] > 0 else None
        v["access_since"] = a["since"].isoformat() if a and a["since"] and v["open"] > 0 else None
    by_item: dict[str, dict] = {}
    for zid in open_zones:
        for i in zones[zid]["items"]:
            if i["remaining"] > 0:
                s = by_item.setdefault(i["item_type"], {"zones": 0, "remaining": 0})
                s["zones"] += 1
                s["remaining"] += i["remaining"]
    cut_off = [z for z in open_zones if zones[z]["zone_access"] == "isolated"]
    maybe = [z for z in open_zones if zones[z]["zone_access"] == "possibly_isolated"]
    reason = read_only_reason(run)
    return {"run_id": str(run.id), "mode": run.mode.value, "at": at.isoformat(), "label": LABEL,
            "writable": reason is None, "blocked_reason": reason, "items": [i.value for i in ItemType],
            "max_quantity": MAX_QUANTITY, "max_note": MAX_NOTE, "zones": zones,
            "summary": {"zones_with_open_needs": len(open_zones), "by_item": by_item,
                        "open_in_cut_off_zones": len(cut_off), "open_in_possibly_cut_off_zones": len(maybe),
                        "cut_off_zone_ids": sorted(cut_off, key=lambda z: -zones[z]["open"])[:8]}}
