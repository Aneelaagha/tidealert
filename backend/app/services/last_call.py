"""Last call: for each flagged zone, the latest moment a dispatch could still set out before the zone's roads close.

    last call = the zone's cut-off time - the lead time a dispatch needs (reply wait + decision + travel)

The cut-off time is the isolation engine's own: when it first finds every dry road out of the zone flooded (the stored
evidence, see app.services.safety). The lead time is NOT measured here: nothing in this system measures how long a crew
needs, so the operator sets it (three numbers that default to zero), and the answer shows the arithmetic. With no lead set,
"last call" is simply the cut-off time.

What this is not, said plainly:
- It is a replay: the cut-off times are the engine's RECORDED results, known in hindsight, standing in for a forecast. A live
  system would need a river-stage forecast, and its last calls could be no better than that forecast. At a slider time the
  board therefore reads some times later than the slider (that is the point of a countdown), unlike the rest of the page,
  which never reads the future; every row that does says so (`hindsight`).
- It is per street-block zone, not per household: Harvey has no households, and the households in the scenarios are
  synthetic and sit in no real basin. The probe cascade (listening engine) is therefore not wired to it: nothing is sent, and
  no probe is scheduled at a last call.
- "Cut off" means no dry ROAD route out, as the engine finds it. It says nothing about phones, neighbours, boats or
  aircraft, and roads reopen: a zone the engine later finds reconnected is shown as reconnected, not as lost.
- It is only as good as the flood surface and the road graph. A zone the engine could not assess, or only "possibly"
  isolated, has no last call (unknown stays unknown): only zones with a recorded cut-off are listed.
"""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Case, Run, Zone
from app.models.case_engine_contribution import CaseEngineContribution, ContributionDirection, Engine

MAX_LEAD_MINUTES = 24 * 60
LABEL = ("Last call = the engine's recorded cut-off time minus the lead time you set. In this replay the cut-off times are "
         "known in hindsight and stand in for a forecast: a live system needs a river forecast. Per zone, not per household. "
         "'Cut off' means no dry road route out, as the engine finds it.")


class LastCallError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


def check_lead(reply: int, decision: int, travel: int) -> int:
    for name, v in (("reply wait", reply), ("decision time", decision), ("travel time", travel)):
        if not 0 <= v <= MAX_LEAD_MINUTES:
            raise LastCallError(422, f"{name} must be a whole number of minutes from 0 to {MAX_LEAD_MINUTES}")
    return reply + decision + travel


def evidence(db: Session, run: Run) -> dict[str, list[tuple[datetime, bool]]]:
    """Each flagged zone's isolation evidence over the whole run, oldest first: (when first observed, is it a cut-off row)."""
    rows = db.execute(
        select(Case.zone_id, CaseEngineContribution.first_observed_at, CaseEngineContribution.direction)
        .join(CaseEngineContribution, CaseEngineContribution.case_id == Case.id)
        .where(Case.run_id == run.id, CaseEngineContribution.engine == Engine.isolation,
               CaseEngineContribution.direction.in_((ContributionDirection.supports, ContributionDirection.contradicts)))).all()
    out: dict[str, list] = defaultdict(list)
    for zid, t, d in rows:
        out[str(zid)].append((t, d == ContributionDirection.supports))
    return {z: sorted(v, key=lambda x: x[0]) for z, v in out.items()}


def zone_status(events: list[tuple[datetime, bool]], at: datetime, lead: timedelta) -> Optional[dict]:
    """A zone's last-call status at `at`, from its evidence (see the module docstring). None: nothing to say."""
    known = [e for e in events if e[0] <= at]
    cut_now = bool(known) and known[-1][1]
    if cut_now:  # cut off now: since the start of this run of cut-off rows
        i = len(known) - 1
        while i > 0 and known[i - 1][1]:
            i -= 1
        return {"status": "cut_off", "cutoff_at": known[i][0], "last_call_at": known[i][0] - lead, "hindsight": False}
    nxt = next((e[0] for e in events if e[0] > at and e[1]), None)
    if nxt is not None:
        last = nxt - lead
        return {"status": "counting" if at < last else "passed", "cutoff_at": nxt, "last_call_at": last, "hindsight": True,
                "was_reconnected": bool(known)}
    if known:  # the last evidence at or before `at` is a reconnection and no cut-off follows
        return {"status": "reconnected", "cutoff_at": None, "last_call_at": None, "hindsight": False}
    return None


def board(db: Session, run: Run, at: datetime, reply: int = 0, decision: int = 0, travel: int = 0) -> dict:
    total = check_lead(reply, decision, travel)
    lead = timedelta(minutes=total)
    ev = evidence(db, run)
    names = {str(z.id): z.name for z in db.scalars(select(Zone).where(Zone.id.in_(list(ev))))} if ev else {}
    zones = []
    for zid, events in ev.items():
        s = zone_status(events, at, lead)
        if s is None:
            continue
        mins = lambda t: None if t is None else int((t - at).total_seconds() // 60)  # noqa: E731
        zones.append({"zone_id": zid, "zone_name": names.get(zid, zid[:8]), "status": s["status"],
                      "cutoff_at": s["cutoff_at"].isoformat() if s["cutoff_at"] else None,
                      "last_call_at": s["last_call_at"].isoformat() if s["last_call_at"] else None,
                      "minutes_to_last_call": mins(s["last_call_at"]) if s["status"] == "counting" else None,
                      "minutes_to_cutoff": mins(s["cutoff_at"]) if s["status"] in ("counting", "passed") else None,
                      "hindsight": s["hindsight"], "was_reconnected": s.get("was_reconnected", False)})
    order = {"counting": 0, "passed": 1, "cut_off": 2, "reconnected": 3}
    zones.sort(key=lambda z: (order[z["status"]], z["minutes_to_last_call"] if z["status"] == "counting" else
                              (z["minutes_to_cutoff"] if z["status"] == "passed" else 0), z["zone_id"]))
    counts = {k: sum(1 for z in zones if z["status"] == k) for k in order}
    available = bool(ev)
    return {"run_id": str(run.id), "mode": run.mode.value, "at": at.isoformat(), "label": LABEL, "available": available,
            "reason": None if available else "The isolation engine has not run on this run (no road network or flood surface), "
                                             "so no zone has a cut-off time and none has a last call. Unknown stays unknown.",
            "lead": {"reply_minutes": reply, "decision_minutes": decision, "travel_minutes": travel, "total_minutes": total,
                     "note": "Set by you, not measured: nothing in this system measures how long a dispatch needs."},
            "counts": counts, "zones": zones}
