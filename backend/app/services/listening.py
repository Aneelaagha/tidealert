"""Listening engine: the probe cascade, survivor reports, and nominated-neighbor prompts (spec §2).

Probe cascade, per check-in (all rows are ProbeResponse, linked by
parent_probe_id to the check-in SMS they escalate or follow up):

    check-in SMS --(late for this household)--> voice call --(VOICE_TIMEOUT)-->
    neighbor prompt to the household's nominee --(NEIGHBOR_TIMEOUT)--> exhausted

- "Late" for the SMS is the household's own silence baseline (late_after);
  with too little history, DEFAULT_SMS_TIMEOUT.
- A reply on SMS or the voice call ends the cascade. "OK" closes it; "HELP"
  (I need help) sends a depth follow-up asking ankle / knee / waist.
- A household with no nominated neighbor goes straight from an unanswered
  voice call to exhausted. An exhausted cascade stays open: a late reply from
  the household is still recorded.
- The nominated neighbor's reply is a second, independent signal about the
  household: SEEN_OK (explains the silence), TROUBLE (confirms it), CANT_SEE.

Survivor-as-sensor: every depth reply becomes a visible Signal (type
"reported", variable "depth_reported"). A single report never changes the
zone. When CORROBORATION_MIN or more different households in the same zone
report within CORROBORATION_WINDOW, the reports are marked corroborating
(ProbeResponse.is_corroborating, Signal.corroborates_signal_id) and the
zone's risk_level is raised (never lowered) to the level of the depth at
least two of them reached (DEPTH_RISK).

Messages go through a transport. Nothing is sent for real yet: there are no
SMS/voice credentials. SimulatedTransport plays scripted replies for
synthetic households, and they only become visible once the sweep's clock
passes the reply time. TwilioTransport is a placeholder.

The timeouts, the corroboration window and the depth-to-risk mapping are
placeholders, not calibrated against real households.
"""
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Protocol

from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Household, ProbeResponse, Signal, Zone
from app.models.data_source import SignalType
from app.models.probe_response import DepthReported, ProbeChannel, ProbePurpose
from app.models.zone import RiskLevel
from app.services import silence_baseline
from app.services.data_sources import ensure_data_source

log = logging.getLogger(__name__)

DEFAULT_SMS_TIMEOUT = timedelta(minutes=15)
VOICE_TIMEOUT = timedelta(minutes=10)
NEIGHBOR_TIMEOUT = timedelta(minutes=30)
CORROBORATION_WINDOW = timedelta(hours=2)
CORROBORATION_MIN = 2
DEPTH_ORDER = [DepthReported.ankle, DepthReported.knee, DepthReported.waist]
DEPTH_RISK = {DepthReported.ankle: RiskLevel.elevated, DepthReported.knee: RiskLevel.extreme,
              DepthReported.waist: RiskLevel.extreme}
RISK_ORDER = [RiskLevel.safe, RiskLevel.elevated, RiskLevel.extreme]

# Reply codes.
OK, HELP = "OK", "HELP"
SEEN_OK, TROUBLE, CANT_SEE = "SEEN_OK", "TROUBLE", "CANT_SEE"


# ------------------------------------------------------------------ transports
class Transport(Protocol):
    def send(self, probe: ProbeResponse, text: str) -> None:
        """Send one message. Replies are recorded on the probe when they arrive."""


@dataclass
class ScriptedReply:
    after: timedelta
    code: str
    depth: Optional[DepthReported] = None


@dataclass
class SimulatedTransport:
    """Replays scripted replies for synthetic households: (household_id, purpose, channel) -> reply.

    The reply is written onto the probe with its future responded_at; the engine only sees it once the
    sweep's clock reaches that time. No script means no reply.
    """
    scripts: dict = field(default_factory=dict)
    outbox: list = field(default_factory=list)

    def send(self, probe: ProbeResponse, text: str) -> None:
        self.outbox.append((probe.sent_at, probe.channel.value, probe.purpose.value, text))
        reply = self.scripts.get((probe.household_id, probe.purpose, probe.channel))
        if reply is not None:
            probe.responded_at = probe.sent_at + reply.after
            probe.response_code = reply.code
            probe.depth_reported = reply.depth


class TwilioTransport:
    """Placeholder: live SMS and voice need Twilio credentials, which do not exist yet."""

    def send(self, probe: ProbeResponse, text: str) -> None:
        raise NotImplementedError("Live SMS/voice sending is not implemented (no Twilio credentials)")


# ------------------------------------------------------------------ events
@dataclass
class Event:
    """Something the case matcher may turn into a Case contribution."""
    kind: str  # escalated_voice | escalated_neighbor | exhausted | answered | help | depth | corroborated_depth | neighbor
    at: datetime
    household_id: Optional[uuid.UUID] = None
    zone_id: Optional[uuid.UUID] = None
    root_probe_id: Optional[uuid.UUID] = None
    code: Optional[str] = None
    detail: str = ""
    signal_ids: list = field(default_factory=list)


# ------------------------------------------------------------------ engine
@dataclass
class ListeningEngine:
    db: Session
    transport: Transport
    household_ids: list  # households this engine runs cascades for
    _handled: set = field(default_factory=set)  # (probe_id, what) already turned into events
    # Cascades this engine started. PLACEHOLDER: kept in memory only, so a restart loses open cascades;
    # a live system needs them persisted (e.g. a cascade table). Historical check-ins are never cascades.
    _root_ids: list = field(default_factory=list)
    _source_id: Optional[uuid.UUID] = None

    def _source(self) -> uuid.UUID:
        if self._source_id is None:
            self._source_id = ensure_data_source(
                self.db, name="Listening: household replies", category="survivor_report", cadence_seconds=0,
                stale_after_seconds=6 * 3600, type_default=SignalType.reported, url="n/a",
                license="Household consent (registry)",
                notes="Replies to TideAlert probes. Synthetic until a live registry exists.",
            ).id
        return self._source_id

    def _send(self, household: Household, now: datetime, channel: ProbeChannel, purpose: ProbePurpose,
              parent: Optional[ProbeResponse], text: str) -> ProbeResponse:
        probe = ProbeResponse(id=uuid.uuid4(), household_id=household.id, channel=channel, purpose=purpose,
                              sent_at=now, parent_probe_id=parent.id if parent else None)
        self.transport.send(probe, text)
        self.db.add(probe)
        self.db.flush()
        return probe

    def start_checkin(self, household: Household, now: datetime) -> ProbeResponse:
        root = self._send(household, now, ProbeChannel.sms, ProbePurpose.checkin, None,
                          "TideAlert check-in: are you OK? Reply OK, or HELP if you need help.")
        self._root_ids.append(root.id)
        return root

    def _once(self, probe_id, what) -> bool:
        key = (probe_id, what)
        if key in self._handled:
            return False
        self._handled.add(key)
        return True

    def _sms_timeout(self, root: ProbeResponse) -> timedelta:
        baseline = silence_baseline.household_baseline(self.db, root.household_id, before=root.sent_at)
        late = baseline.late_after_seconds
        return timedelta(seconds=late) if late is not None else DEFAULT_SMS_TIMEOUT

    def advance(self, now: datetime) -> list[Event]:
        """Move every open cascade forward to `now`; return what happened."""
        events: list[Event] = []
        households = {h.id: h for h in self.db.scalars(select(Household).where(Household.id.in_(self.household_ids)))}
        roots = self.db.scalars(
            select(ProbeResponse).where(ProbeResponse.id.in_(self._root_ids), ProbeResponse.sent_at <= now)
            .order_by(ProbeResponse.sent_at)
        ).all()
        for root in roots:
            if (root.id, "closed") in self._handled:
                continue
            household = households[root.household_id]
            children = list(self.db.scalars(select(ProbeResponse).where(ProbeResponse.parent_probe_id == root.id)
                                            .order_by(ProbeResponse.sent_at)))
            by_purpose = {}
            for c in children:
                by_purpose.setdefault((c.purpose, c.channel), c)
            voice = by_purpose.get((ProbePurpose.checkin, ProbeChannel.voice))
            neighbor = by_purpose.get((ProbePurpose.neighbor_prompt, ProbeChannel.neighbor))
            depth_q = by_purpose.get((ProbePurpose.depth_followup, ProbeChannel.sms))
            events += self._advance_one(now, household, root, voice, neighbor, depth_q)
        self.db.flush()
        return events

    def _advance_one(self, now, household, root, voice, neighbor, depth_q) -> list[Event]:
        ev = []
        base = dict(household_id=household.id, zone_id=household.zone_id, root_probe_id=root.id)
        answered = next((p for p in (root, voice) if p is not None and p.responded_at and p.responded_at <= now), None)

        if answered is not None:
            if self._once(answered.id, "answered"):
                elapsed = answered.responded_at - root.sent_at
                ev.append(Event("answered", answered.responded_at, code=answered.response_code,
                                detail=f"answered {answered.response_code} by {answered.channel.value} "
                                       f"{_fmt(elapsed)} after the check-in", **base))
            if answered.response_code == HELP:
                if depth_q is None:
                    self._send(household, now, ProbeChannel.sms, ProbePurpose.depth_followup, root,
                               "How deep is the water where you are? Reply ANKLE, KNEE or WAIST.")
                    ev.append(Event("help", now, code=HELP, detail="replied HELP; depth follow-up sent", **base))
                elif depth_q.responded_at and depth_q.responded_at <= now and depth_q.depth_reported \
                        and self._once(depth_q.id, "depth"):
                    ev += self._record_depth(household, depth_q, base)
            if answered.response_code != HELP or (depth_q is not None and depth_q.responded_at
                                                  and depth_q.responded_at <= now):
                self._handled.add((root.id, "closed"))
            return ev

        if neighbor is not None and neighbor.responded_at and neighbor.responded_at <= now:
            if self._once(neighbor.id, "neighbor"):
                ev.append(Event("neighbor", neighbor.responded_at, code=neighbor.response_code,
                                detail=f"nominated neighbor replied {neighbor.response_code} "
                                       f"{_fmt(neighbor.responded_at - neighbor.sent_at)} after the prompt", **base))
            return ev

        if voice is None:
            if now >= root.sent_at + self._sms_timeout(root):
                self._send(household, now, ProbeChannel.voice, ProbePurpose.checkin, root,
                           "Automated call: this is TideAlert checking you are OK. Press 1 if OK, 2 if you need help.")
                ev.append(Event("escalated_voice", now, detail=f"no SMS reply after {_fmt(now - root.sent_at)}",
                                **base))
        elif neighbor is None:
            if now >= voice.sent_at + VOICE_TIMEOUT:
                nominee = self.db.get(Household, household.nominee_household_id) if household.nominee_household_id \
                    else None
                if nominee is None:
                    if self._once(root.id, "exhausted"):
                        ev.append(Event("exhausted", now, detail="no SMS or voice reply; no nominated neighbor",
                                        **base))
                else:
                    # PLACEHOLDER: households have no street address yet, so the prompt uses coordinates.
                    where = f"the home at ({household.latitude:.5f}, {household.longitude:.5f})"
                    self._send(household, now, ProbeChannel.neighbor, ProbePurpose.neighbor_prompt, root,
                               f"TideAlert: your neighbor hasn't answered a check-in. Can you see {where}? "
                               f"Reply OK if they're fine, TROUBLE if something's wrong, or CANT if you can't see.")
                    ev.append(Event("escalated_neighbor", now,
                                    detail=f"no SMS or voice reply after {_fmt(now - root.sent_at)}; "
                                           f"nominated neighbor prompted", **base))
        elif now >= neighbor.sent_at + NEIGHBOR_TIMEOUT and self._once(root.id, "exhausted"):
            ev.append(Event("exhausted", now, detail="no reply from the household or its nominated neighbor", **base))
        return ev

    # -------------------------------------------------------------- depth reports
    def _record_depth(self, household: Household, probe: ProbeResponse, base: dict) -> list[Event]:
        signal = Signal(id=uuid.uuid4(), source_id=self._source(), signal_type=SignalType.reported,
                        variable="depth_reported", value_text=probe.depth_reported.value,
                        geometry=from_shape(Point(household.longitude, household.latitude), srid=4326),
                        observed_at=probe.responded_at)
        self.db.add(signal)
        self.db.flush()
        probe.signal_id = signal.id
        self.db.flush()  # the corroboration query below must see this report (the session does not autoflush)
        corroborated = self._corroboration(household.zone_id, probe.responded_at)
        note = ("corroborates other reports in this block (see the block's case)" if corroborated else
                "single report: visible, does not change the zone")
        ev = [Event("depth", probe.responded_at, code=probe.depth_reported.value, signal_ids=[signal.id],
                    detail=f"reported {probe.depth_reported.value}-deep water ({note})", **base)]
        if corroborated:
            ev.append(corroborated)
        return ev

    def _corroboration(self, zone_id: uuid.UUID, at: datetime) -> Optional[Event]:
        """If CORROBORATION_MIN+ households in the zone reported within the window, apply it to the zone."""
        rows = self.db.execute(
            select(ProbeResponse, Household)
            .join(Household, Household.id == ProbeResponse.household_id)
            .where(Household.zone_id == zone_id, ProbeResponse.depth_reported.is_not(None),
                   ProbeResponse.signal_id.is_not(None), ProbeResponse.responded_at <= at,
                   ProbeResponse.responded_at >= at - CORROBORATION_WINDOW)
            .order_by(ProbeResponse.responded_at)
        ).all()
        latest = {}
        for probe, household in rows:  # one report per household: its latest
            latest[household.id] = probe
        if len(latest) < CORROBORATION_MIN:
            return None
        reports = sorted(latest.values(), key=lambda p: p.responded_at)
        depths = sorted((p.depth_reported for p in reports), key=DEPTH_ORDER.index, reverse=True)
        agreed = depths[CORROBORATION_MIN - 1]  # the depth at least CORROBORATION_MIN households reached
        first_signal = reports[0].signal_id
        for p in reports:
            p.is_corroborating = True
            if p.signal_id != first_signal:
                self.db.get(Signal, p.signal_id).corroborates_signal_id = first_signal
        zone = self.db.get(Zone, zone_id)
        before = zone.risk_level
        target = DEPTH_RISK[agreed]
        if RISK_ORDER.index(target) > RISK_ORDER.index(before):
            zone.risk_level = target
        change = f"zone risk_level {before.value} -> {zone.risk_level.value}" if zone.risk_level != before \
            else f"zone risk_level stays {before.value}"
        return Event("corroborated_depth", at, zone_id=zone_id, code=agreed.value,
                     signal_ids=[p.signal_id for p in reports],
                     detail=f"{len(reports)} households reported flood depth within "
                            f"{_fmt(reports[-1].responded_at - reports[0].responded_at)} "
                            f"({', '.join(p.depth_reported.value for p in reports)}); at least {CORROBORATION_MIN} "
                            f"reached {agreed.value}; {change}")


def _fmt(delta: timedelta) -> str:
    s = delta.total_seconds()
    return f"{s:.0f} s" if s < 120 else f"{s / 60:.0f} min"
