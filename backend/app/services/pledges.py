"""The donation portal: donors OFFER supplies against open, operator-entered needs (app.services.needs), and an
operator records what arrived. It moves no goods and takes no money, checks no offer is real, and stores no contact
details: an offer is a claim, like the need it answers.

- A pledge is open from `offered_at` until an operator closes it as received or withdrawn; a past time reads the
  offers open then. Offered quantity is spoken for: a pledge may not exceed what is open and not already pledged in
  that zone, and fulfilling or withdrawing a need may not eat into an open pledge (app.services.needs.record).
- Receiving a pledge records a `fulfilled` need entry of its quantity, in the same transaction (a 409 if the need
  has since shrunk below it). Withdrawing returns the quantity to the unpledged need.
- Where entries are allowed is the needs board's rule: refused on a replay (422); mixed, scenario and live runs.
- No login: `donor` and the closing `actor` are free text, so anyone can offer and anyone can close an offer. The
  donor name must hold no contact details; that guard is lexical (an @, a URL, or a run of 7+ digits), so it
  catches the obvious and not every form of one.
- An offer to a zone the isolation engine finds cut off is allowed and flagged, never hidden: whether supplies can
  get there is the question the board raises, not one this module can answer.
"""
import re
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NeedEvent, Pledge, Run, Zone
from app.models.need_event import NeedEventKind
from app.models.pledge import PledgeClose
from app.models.zone_need import ItemType
from app.services import map_state, needs
from app.services.needs import NeedError, read_only_reason

MAX_DONOR = 60
MAX_NOTE = needs.MAX_NOTE
CONTACT = re.compile(r"@|https?://|www\.|(?:\d[\s().+-]*){7,}", re.I)
LABEL = ("An offer typed in by a donor. Nothing checks it is real, no goods move and no money is taken here, and "
         "no contact details are kept.")


def _no_contact(what: str, text: str) -> None:
    if CONTACT.search(text):
        raise NeedError(422, f"{what} must not hold contact details (an email, a link or a phone number): none are kept")


def _latest_need_event(db: Session, run_id, zone_id, item_type) -> Optional[NeedEvent]:
    return db.scalars(select(NeedEvent).where(NeedEvent.run_id == run_id, NeedEvent.zone_id == zone_id,
                                              NeedEvent.item_type == item_type)
                      .order_by(NeedEvent.at.desc(), NeedEvent.created_at.desc())).first()


def _remaining(db: Session, run_id, zone_id, item_type) -> int:
    events = list(db.scalars(select(NeedEvent).where(NeedEvent.run_id == run_id, NeedEvent.zone_id == zone_id,
                                                     NeedEvent.item_type == item_type)))
    return sum(e.quantity if e.event == NeedEventKind.requested else -e.quantity for e in events)


def offer(db: Session, run: Run, zone_id, item_type: ItemType, quantity: int, donor: str,
          at: Optional[datetime] = None, note: str = "") -> Pledge:
    reason = read_only_reason(run)
    if reason:
        raise NeedError(422, reason)
    donor = (donor or "").strip()
    if not donor:
        raise NeedError(422, "donor is required: a name or organisation to show (no contact details)")
    if len(donor) > MAX_DONOR:
        raise NeedError(422, f"donor is limited to {MAX_DONOR} characters")
    _no_contact("donor", donor)
    note = (note or "").strip()
    if len(note) > MAX_NOTE:
        raise NeedError(422, f"note is limited to {MAX_NOTE} characters")
    _no_contact("note", note)
    if not 0 < quantity <= needs.MAX_QUANTITY:
        raise NeedError(422, f"quantity must be a whole number from 1 to {needs.MAX_QUANTITY:,}")
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
    db.refresh(zone, with_for_update=True)  # the same per-zone lock the need entries take
    latest = _latest_need_event(db, run.id, zone.id, item_type)
    if latest is None or _remaining(db, run.id, zone.id, item_type) <= 0:
        raise NeedError(409, f"no open need for {item_type.value} in this zone: an offer answers a need an "
                             "operator has entered")
    if when < latest.at:
        raise NeedError(422, f"at {when.isoformat()} is before this item's latest need entry in the zone "
                             f"({latest.at.isoformat()})")
    free = _remaining(db, run.id, zone.id, item_type) - needs.open_pledged(db, run.id, zone.id, item_type)
    if quantity > free:
        raise NeedError(409, f"only {max(free, 0)} of {item_type.value} is open and not already pledged in this "
                             f"zone; cannot offer {quantity}")
    row = Pledge(run_id=run.id, zone_id=zone.id, item_type=item_type, quantity=quantity, donor=donor,
                 offered_at=when, note=note or None)
    db.add(row)
    db.flush()
    return row


def close(db: Session, pledge_id, kind: PledgeClose, actor: str, at: Optional[datetime] = None,
          note: str = "") -> tuple[Pledge, Run]:
    pledge = db.get(Pledge, pledge_id)
    if pledge is None:
        raise NeedError(404, "pledge not found")
    run = db.get(Run, pledge.run_id)
    reason = read_only_reason(run)
    if reason:
        raise NeedError(422, reason)
    actor = (actor or "").strip()
    if not actor:
        raise NeedError(422, "actor is required (who is closing this; there is no authentication yet)")
    zone = db.get(Zone, pledge.zone_id)
    db.flush()
    db.refresh(zone, with_for_update=True)
    db.refresh(pledge, with_for_update=True)
    if pledge.closed_at is not None:
        raise NeedError(409, f"this pledge was already closed as {pledge.closed_kind.value}")
    try:
        when = map_state.resolve_at(run, at)
    except map_state.TimeOutOfWindow as exc:
        raise NeedError(422, str(exc))
    if when < pledge.offered_at:
        raise NeedError(422, f"at {when.isoformat()} is before the pledge was offered ({pledge.offered_at.isoformat()})")
    if kind == PledgeClose.received:
        needs.record(db, run, pledge.zone_id, pledge.item_type, NeedEventKind.fulfilled, pledge.quantity, actor,
                     at=when, note=f"received from pledge by {pledge.donor}", pledged_exempt=pledge.quantity)
    pledge.closed_at, pledge.closed_kind, pledge.closed_by = when, kind, actor
    db.flush()
    return pledge, run
