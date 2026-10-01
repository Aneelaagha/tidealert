"""Case matcher: a periodic sweep that opens and updates Cases from the isolation, silence and listening engines.

Every CADENCE (15 minutes, the spec's sweep window) the scheduler calls
CaseSweeper.sweep(now) for each gauge. A sweep uses only information as of
`now`:

- Isolation: the isolation engine's state at `now` (isolation_step with the
  river level at that timestep; unknown roads passable, so isolation is
  confirmed). A newly isolated zone opens a Case. While it stays isolated the
  supporting contribution is refreshed (observed_at, confidence). A change of
  mechanism (stranded -> submerged) or a renewed isolation adds a supporting
  contribution; a reconnection adds a contradicting one. The engine never
  resolves or closes a Case: that is a human decision.
- Silence: each household's most recent check-in SMS as of `now` (older
  unanswered ones are moot once a later one is answered), if neither it nor
  the voice call escalating it has been answered by `now`, judged against the
  household's own baseline from earlier check-ins (silence_baseline). A late
  household adds a supporting contribution, refreshed while the silence
  lasts, to its zone's open isolation Case or its own household Case; its
  eventual reply adds a contradicting one.
- Listening (when a ListeningEngine is attached): probe cascades advance
  first (SMS -> voice -> nominated neighbor). A help request joins the zone's
  open isolation Case or opens a household Case; a single depth report is
  only added to the household's own Case and never changes the zone; 2+
  corroborating depth reports join the zone's isolation Case or open a zone
  Case; the nominated neighbor's reply supports (TROUBLE), contradicts
  (SEEN_OK) or is neutral (CANT_SEE); cascade steps are procedural.

After the confidence words, the task rules (app.services.task_rules) create
or update each Case's task: a pending task for a Case with fresh support,
flagged verify_before_dispatch when its evidence goes stale. Nothing is
dispatched automatically.

Every contribution carries a direction (supports / contradicts / neutral /
procedural), the confidence derived by its engine, and when it was observed.
At the end of each sweep every case's confidence_word is recomputed from its
contributions with time decay (app.services.confidence), so stale_verify is
set when no supporting evidence is fresh or the latest evidence contradicts
the case.

Replay mode steps a clock through a past event window without waiting. Live
mode needs a household registry and probe cascade, which do not exist yet.

Caveat for replay: the river level at each step comes from the published
USGS record, which includes values estimated after the event, and a rating
curve fitted to the whole event. A live system would only have had
provisional data at the time.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import AsyncIterator, Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Case, CaseEngineContribution, Household, ProbeResponse, Zone
from app.models.case import CaseStatus, ConfidenceWord
from app.models.case_engine_contribution import ContributionDirection, Engine
from app.models.probe_response import ProbeChannel
from app.services import isolation_engine as engine
from app.services import silence_baseline
from app.services.confidence import case_confidence
from app.services.task_rules import apply_task_rules
from app.services.isolation_cases import clear_cases, isolation_confidence, isolation_mechanism
from app.services.listening import (
    CANT_SEE, SEEN_OK, SOURCE_BASE, TROUBLE, ListeningEngine, corroborated_depth_confidence,
)
from app.services.river_driver import SiteContext

log = logging.getLogger(__name__)

CADENCE = timedelta(minutes=15)
SUPPORTS, CONTRADICTS = ContributionDirection.supports, ContributionDirection.contradicts
NEUTRAL, PROCEDURAL = ContributionDirection.neutral, ContributionDirection.procedural


def replay_run_name(start: datetime, end: datetime, tz) -> str:
    """Name of a replay run over this window, e.g. backtest:2017-08-25..2017-09-02."""
    return f"backtest:{start.astimezone(tz).date()}..{(end - timedelta(seconds=1)).astimezone(tz).date()}"


def replay_source(start: datetime, end: datetime, tz, label: str) -> str:
    """Source label for replayed cases, e.g. backtest:2017-08-25..2017-09-02:USGS-08074500."""
    return f"{replay_run_name(start, end, tz)}:{label}"


def _fmt_s(seconds: float) -> str:
    return f"{seconds:.0f} s" if seconds < 120 else f"{seconds / 60:.0f} min"


@dataclass
class SweepResult:
    now: datetime
    opened: int = 0
    updated: int = 0
    contributions: int = 0
    tasks_created: int = 0
    tasks_changed: int = 0
    events: list = field(default_factory=list)


@dataclass
class _Tracked:
    case: Case
    state: str  # last isolation mechanism, or "reconnected"
    mech: object = None  # mechanism behind the live supporting contribution
    live: Optional[CaseEngineContribution] = None  # the isolation evidence being refreshed while it holds


@dataclass
class _Silent:
    case: Case
    baseline: object
    live: CaseEngineContribution


@dataclass
class CaseSweeper:
    """Opens and updates Cases for one gauge (isolation) and its zones' households (silence, listening)."""

    db: Session
    source: str
    tz: object
    run_id: object  # the Run every case this sweeper opens belongs to (app.services.runs.ensure_run)
    ctx: Optional[SiteContext] = None  # isolation; None for a sweep without a gauge
    household_zone_ids: list = field(default_factory=list)
    listening: Optional[ListeningEngine] = None  # runs probe cascades; None = no cascades
    _zone_cases: dict = field(default_factory=dict)  # zone_id -> _Tracked (isolation cases)
    _household_cases: dict = field(default_factory=dict)  # household_id -> household Case
    _flagged_probes: dict = field(default_factory=dict)  # check-in probe_id -> _Silent
    _households: dict = field(default_factory=dict)  # household_id -> Household, loaded once at start
    _zone_listening_cases: dict = field(default_factory=dict)  # zone_id -> zone Case opened by listening
    _cascade_cases: dict = field(default_factory=dict)  # check-in probe_id -> Case a listening signal attached to
    _cases: list = field(default_factory=list)  # every case this sweeper opened (for the confidence word)
    _urgent: dict = field(default_factory=dict)  # id(case) -> why its task is urgent (help request, neighbor trouble)

    def start(self, replace: bool = True) -> None:
        if replace:
            removed = clear_cases(self.db, self.source)
            self.db.commit()
            if removed:
                log.info("%s: replaced %d existing cases", self.source, removed)
        if self.ctx is not None:
            self.household_zone_ids = [z.id for z in self.ctx.zones]
            self._highway_class = list(self.ctx.segments["highway_class"])
            self._library_max = float(self.ctx.fim.stage_ft.max()) if self.ctx.fim is not None else None
        # The registry does not change during a replay: load the swept households once.
        if self.household_zone_ids:
            self._households = {h.id: h for h in self.db.scalars(
                select(Household).where(Household.zone_id.in_(self.household_zone_ids)))}

    # ---------------------------------------------------------------- shared
    def _new_case(self, now: datetime, **fields) -> Case:
        case = Case(status=CaseStatus.open, source=self.source, run_id=self.run_id,
                    confidence_word=ConfidenceWord.single_source,
                    opened_at=now, last_contribution_at=now, **fields)
        self.db.add(case)
        self._cases.append(case)
        return case

    def _contribute(self, case: Case, which: Engine, now: datetime, fragment: str, confidence: float,
                    direction: ContributionDirection, sources: int = 1) -> CaseEngineContribution:
        if direction in (NEUTRAL, PROCEDURAL):
            confidence = 0.0
        contribution = CaseEngineContribution(
            engine=which, rule_fragment=f"[{now.isoformat()}] {fragment}", engine_confidence=confidence,
            direction=direction, first_observed_at=now, observed_at=now, independent_sources=sources)
        case.contributions.append(contribution)
        case.last_contribution_at = now
        return contribution

    # ---------------------------------------------------------------- isolation
    def _iso_confidence(self, i: int, mech):
        ctx = self.ctx
        return isolation_confidence(ctx.net, ctx.river.confidence, ctx.stage.provenance[i],
                                    float(ctx.stage.stage_ft[i]), self._library_max, mech,
                                    river_level=float(ctx.river.level[i]))

    def _isolation(self, now: datetime, result: SweepResult) -> None:
        ctx = self.ctx
        i = ctx.times.index(now)
        level = float(ctx.river.level[i])
        state = engine.isolation_step(ctx.net, ctx.bounds, ctx.evaluated, level)
        for k, zone in enumerate(ctx.zones):
            tracked = self._zone_cases.get(zone.id)
            if state.isolated[k]:
                current = "stranded" if state.stranded[k] else "submerged"
                if tracked is None:
                    mech = isolation_mechanism(ctx.net, ctx.bounds, k, level, self._highway_class)
                    case, live = self._open_isolation_case(zone, now, i, mech)
                    self._zone_cases[zone.id] = _Tracked(case, mech.state, mech, live)
                    result.opened += 1
                elif tracked.state != current:
                    mech = isolation_mechanism(ctx.net, ctx.bounds, k, level, self._highway_class)
                    conf = self._iso_confidence(i, mech)
                    verb = "isolated again" if tracked.state == "reconnected" else f"now {mech.state}"
                    tracked.live = self._contribute(tracked.case, Engine.isolation, now,
                                                    f"{verb}: {self._fragment(mech, i)}; {conf.describe()}",
                                                    conf.value, SUPPORTS)
                    tracked.state, tracked.mech = mech.state, mech
                    result.contributions += 1
                else:
                    # Still isolated the same way: the engine re-confirms its evidence this sweep. The cut
                    # may now run along different roads, all flooded by covered samples (coverage 1.0 by
                    # construction), so only stage provenance and library range are re-scored.
                    conf = self._iso_confidence(i, None)
                    tracked.live.observed_at = now
                    tracked.live.engine_confidence = conf.value
                    tracked.case.last_contribution_at = now
                    result.updated += 1
            elif tracked is not None and tracked.state != "reconnected":
                conf = self._iso_confidence(i, None)
                self._contribute(tracked.case, Engine.isolation, now,
                                 f"reconnected: a route to the main road network is open again at stage "
                                 f"{ctx.stage.stage_ft[i]:.2f} ft; {conf.describe()}", conf.value, CONTRADICTS)
                tracked.state, tracked.mech, tracked.live = "reconnected", None, None
                result.contributions += 1

    def _fragment(self, mech, i: int) -> str:
        ctx = self.ctx
        level = f"{ctx.river.level[i]:.1f} {ctx.river.units.split(' ')[0]}"
        where = (f"river level {level} at stage {ctx.stage.stage_ft[i]:.2f} ft; {ctx.river.method}; "
                 f"confirmed with unknown roads passable")
        if mech.state == "stranded":
            classes = ", ".join(f"{n} {c}" for c, n in sorted(mech.exit_road_classes.items()))
            return (f"stranded: {mech.dry_boundary_roads}/{mech.boundary_roads} boundary roads dry; "
                    f"{mech.exit_roads_flooded} exit roads flooded ({classes}); {where}")
        return f"submerged: {mech.boundary_roads}/{mech.boundary_roads} boundary roads flooded; {where}"

    def _open_isolation_case(self, zone: Zone, now: datetime, i: int, mech):
        ctx = self.ctx
        when = now.astimezone(self.tz).strftime("%Y-%m-%d %H:%M %Z")
        if mech.state == "stranded":
            dry = (f"all {mech.boundary_roads}" if mech.dry_boundary_roads == mech.boundary_roads else
                   f"{mech.dry_boundary_roads} of its {mech.boundary_roads}")
            exits = {1: "the only road", 2: "both roads"}.get(mech.exit_roads_flooded,
                                                              f"all {mech.exit_roads_flooded} roads")
            how = f"{dry} boundary roads stayed dry, but {exits} leading out of its neighborhood flooded"
        else:
            how = ("its only boundary road flooded" if mech.boundary_roads == 1 else
                   f"all {mech.boundary_roads} of its boundary roads flooded")
        caveat = " (lower-confidence HAND river model)" if ctx.river.confidence != "primary" else ""
        case = self._new_case(
            now, zone_id=zone.id,
            inference_sentence=(f"Street block with {zone.population_count} residents was cut off from the main "
                                f"road network at {when}: {how}, with USGS {ctx.site.site_id} at "
                                f"{ctx.stage.stage_ft[i]:.2f} ft{caveat}."))
        conf = self._iso_confidence(i, mech)
        live = CaseEngineContribution(engine=Engine.isolation, rule_fragment=f"{self._fragment(mech, i)}; {conf.describe()}",
                                      engine_confidence=conf.value, direction=SUPPORTS, first_observed_at=now,
                                      observed_at=now,
                                      independent_sources=1)
        case.contributions.append(live)
        return case, live

    # ---------------------------------------------------------------- silence
    def _silence(self, now: datetime, result: SweepResult) -> None:
        households = self._households
        if not households:
            return
        # Only each household's most recent check-in as of `now` can make it silent now: once a later
        # probe is answered, an older unanswered one is moot.
        latest = self.db.scalars(
            select(ProbeResponse)
            .where(ProbeResponse.household_id.in_(list(households)), ProbeResponse.sent_at <= now,
                   ProbeResponse.parent_probe_id.is_(None), silence_baseline.checkin_sms_filter())
            .distinct(ProbeResponse.household_id)
            .order_by(ProbeResponse.household_id, ProbeResponse.sent_at.desc())
        ).all()
        pending = [p for p in latest if not self._answered_by(p, now)]
        flagged = list(self.db.scalars(select(ProbeResponse).where(ProbeResponse.id.in_(list(self._flagged_probes)))))
        probes = {p.id: p for p in flagged + pending}.values()
        for probe in probes:
            silent = self._flagged_probes.get(probe.id)
            elapsed = (now - probe.sent_at).total_seconds()
            if silent is not None:
                answer = self._answered_by(probe, now)
                if answer is not None:
                    took = (answer.responded_at - probe.sent_at).total_seconds()
                    self._contribute(silent.case, Engine.silence, now,
                                     f"responded: check-in {str(probe.id)[:8]} answered {answer.response_code or ''} "
                                     f"by {answer.channel.value} after {_fmt_s(took)}; confidence "
                                     f"{SOURCE_BASE[answer.channel]:.2f} = source base for a direct {answer.channel.value} "
                                     f"reply", SOURCE_BASE[answer.channel], CONTRADICTS)
                    del self._flagged_probes[probe.id]
                    result.contributions += 1
                else:
                    # Still silent: the engine re-confirms, with z (and so confidence) growing.
                    verdict = silence_baseline.evaluate(silent.baseline, elapsed)
                    silent.live.engine_confidence = silence_baseline.silence_confidence(silent.baseline, verdict).value
                    silent.live.observed_at = now
                continue
            baseline = silence_baseline.household_baseline(self.db, probe.household_id, before=probe.sent_at)
            verdict = silence_baseline.evaluate(baseline, elapsed)
            if verdict.status != "late":
                continue
            conf = silence_baseline.silence_confidence(baseline, verdict)
            household = households[probe.household_id]
            fragment = (f"late: probe {str(probe.id)[:8]} unanswered after {_fmt_s(elapsed)}; this household's "
                        f"median {_fmt_s(baseline.median_seconds)}, late after {_fmt_s(verdict.late_after_seconds)} "
                        f"(z {verdict.z:+.1f}, {baseline.answered} earlier answers); {conf.describe()}")
            tracked = self._zone_cases.get(household.zone_id)
            if tracked is not None and tracked.state != "reconnected":
                case = tracked.case  # matching: a silent household inside a zone the isolation engine has open
            elif household.id in self._household_cases:
                case = self._household_cases[household.id]
            else:
                when = probe.sent_at.astimezone(self.tz).strftime("%Y-%m-%d %H:%M %Z")
                case = self._new_case(
                    now, zone_id=household.zone_id, household_id=household.id,
                    inference_sentence=(f"Household has not answered a check-in sent at {when} after "
                                        f"{_fmt_s(elapsed)}; it usually answers within "
                                        f"{_fmt_s(baseline.median_seconds)}."))
                self._household_cases[household.id] = case
                result.opened += 1
            live = self._contribute(case, Engine.silence, now, fragment, conf.value, SUPPORTS)
            self._flagged_probes[probe.id] = _Silent(case, baseline, live)
            result.contributions += 1

    def _answered_by(self, checkin: ProbeResponse, now: datetime) -> Optional[ProbeResponse]:
        """The reply to a check-in received by `now`, on the SMS itself or the voice call escalating it."""
        candidates = [checkin] + list(self.db.scalars(
            select(ProbeResponse).where(ProbeResponse.parent_probe_id == checkin.id,
                                        ProbeResponse.channel == ProbeChannel.voice)))
        answered = [p for p in candidates if p.responded_at is not None and p.responded_at <= now]
        return min(answered, key=lambda p: p.responded_at) if answered else None

    # ---------------------------------------------------------------- listening
    def _household_case(self, household_id, root_probe_id) -> Optional[Case]:
        silent = self._flagged_probes.get(root_probe_id)
        return ((silent.case if silent else None) or self._cascade_cases.get(root_probe_id)
                or self._household_cases.get(household_id))

    def _listening(self, events: list, now: datetime, result: SweepResult) -> None:
        for ev in events:
            if ev.kind == "help":
                self._listening_help(ev, now, result)
            elif ev.kind == "depth":
                case = self._household_case(ev.household_id, ev.root_probe_id)
                if case is not None:  # household-level detail only; the zone is not touched
                    base = SOURCE_BASE[ev.channel]
                    self._contribute(case, Engine.listening, now,
                                     f"{ev.detail}; confidence {base:.2f} = source base ({ev.channel.value}) x 1 report",
                                     base, SUPPORTS)
                    result.contributions += 1
            elif ev.kind == "corroborated_depth":
                self._listening_corroborated(ev, now, result)
            elif ev.kind == "neighbor":
                self._listening_neighbor(ev, now, result)
            elif ev.kind in ("escalated_voice", "escalated_neighbor", "exhausted"):
                case = self._household_case(ev.household_id, ev.root_probe_id)
                if case is not None:
                    self._contribute(case, Engine.listening, now, f"cascade {ev.kind}: {ev.detail}", 0.0, PROCEDURAL)
                    result.contributions += 1

    def _listening_help(self, ev, now: datetime, result: SweepResult) -> None:
        base = SOURCE_BASE[ev.channel]
        fragment = f"help request: {ev.detail}; confidence {base:.2f} = source base ({ev.channel.value})"
        tracked = self._zone_cases.get(ev.zone_id)
        case = self._household_case(ev.household_id, ev.root_probe_id)
        if case is None and tracked is not None and tracked.state != "reconnected":
            case = tracked.case
        if case is None:
            household = self._households[ev.household_id]
            case = self._new_case(
                now, zone_id=household.zone_id, household_id=household.id,
                inference_sentence="Household replied that it needs help; a water-depth question has been sent.")
            self._household_cases[household.id] = case
            result.opened += 1
        self._contribute(case, Engine.listening, now, fragment, base, SUPPORTS)
        self._urgent.setdefault(id(case), "household asked for help")
        self._cascade_cases.setdefault(ev.root_probe_id, case)
        result.contributions += 1

    def _listening_corroborated(self, ev, now: datetime, result: SweepResult) -> None:
        conf = corroborated_depth_confidence(ev.depths)
        k = len(ev.depths)
        fragment = (f"corroborated depth reports: {ev.detail}; confidence {conf:.2f} = (1 - (1 - "
                    f"{SOURCE_BASE[ProbeChannel.sms]:.2f})^{k}) x disagreement factor")
        tracked = self._zone_cases.get(ev.zone_id)
        if tracked is not None and tracked.state != "reconnected":
            case = tracked.case
        elif ev.zone_id in self._zone_listening_cases:
            case = self._zone_listening_cases[ev.zone_id]
        else:
            case = self._new_case(
                now, zone_id=ev.zone_id,
                inference_sentence=(f"Several households in this street block independently report flood water "
                                    f"at least {ev.code}-deep."))
            self._zone_listening_cases[ev.zone_id] = case
            result.opened += 1
        self._contribute(case, Engine.listening, now, fragment, conf, SUPPORTS, sources=k)
        result.contributions += 1

    def _listening_neighbor(self, ev, now: datetime, result: SweepResult) -> None:
        case = self._household_case(ev.household_id, ev.root_probe_id)
        direction = {TROUBLE: SUPPORTS, SEEN_OK: CONTRADICTS, CANT_SEE: NEUTRAL}.get(ev.code, NEUTRAL)
        meaning = {TROUBLE: "confirms the silence: neighbor reports something is wrong at the home",
                   SEEN_OK: "explains the silence: neighbor reports the household is OK (case stays open for review)",
                   CANT_SEE: "neighbor could not see the home"}.get(ev.code, f"neighbor replied {ev.code}")
        base = SOURCE_BASE[ProbeChannel.neighbor]
        fragment = f"nominated neighbor: {meaning} ({ev.detail}); {direction.value}"
        if case is None and ev.code == TROUBLE:
            household = self._households[ev.household_id]
            case = self._new_case(
                now, zone_id=household.zone_id, household_id=household.id,
                inference_sentence="A household's nominated neighbor reports something is wrong at the home.")
            self._household_cases[household.id] = case
            self._cascade_cases.setdefault(ev.root_probe_id, case)
            result.opened += 1
        if case is not None:
            self._contribute(case, Engine.listening, now, fragment, base, direction)
            if ev.code == TROUBLE:
                self._urgent.setdefault(id(case), "nominated neighbor reports trouble at the home")
            result.contributions += 1

    # ---------------------------------------------------------------- sweep
    def sweep(self, now: datetime) -> SweepResult:
        result = SweepResult(now)
        events = self.listening.advance(now) if self.listening is not None else []
        result.events = events
        if self.ctx is not None:
            self._isolation(now, result)
        self._silence(now, result)
        self._listening(events, now, result)
        for case in self._cases:  # confidence word from decayed evidence as of now, then the task rules
            conf = case_confidence(case, now)
            case.confidence_word = conf.word
            change = apply_task_rules(case, conf, now, urgent=self._urgent.get(id(case)),
                                      household=self._households.get(case.household_id))
            if change == "created":
                result.tasks_created += 1
            elif change == "changed":
                result.tasks_changed += 1
        self.db.commit()
        return result


class ReplayClock:
    """Steps through a past window at the sweep cadence without waiting."""

    def __init__(self, ticks: list[datetime]):
        self.ticks = ticks

    async def __aiter__(self) -> AsyncIterator[datetime]:
        for tick in self.ticks:
            yield tick
            await asyncio.sleep(0)


class LiveClock:
    """Wall-clock sweeps every CADENCE. Needs a live household registry and probe cascade."""

    def __aiter__(self):
        raise NotImplementedError("Live sweeps need a household registry and probe cascade, which do not exist yet")


async def run_scheduler(clock, sweepers: list[CaseSweeper],
                        on_sweep: Optional[Callable[[str, SweepResult], None]] = None) -> None:
    """The periodic sweep: every tick of the clock, run every sweeper once."""
    for sweeper in sweepers:
        sweeper.start()
    async for now in clock:
        for sweeper in sweepers:
            result = sweeper.sweep(now)
            if on_sweep:
                on_sweep(sweeper.source, result)
