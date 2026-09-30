"""Case matcher: a periodic sweep that opens and updates Cases from the isolation and silence engines.

Every CADENCE (15 minutes, the spec's sweep window) the scheduler calls
CaseSweeper.sweep(now) for each gauge. A sweep uses only information as of
`now`:

- Isolation: the isolation engine's state at `now` (isolation_step with the
  river level at that timestep; unknown roads passable, so isolation is
  confirmed). A newly isolated zone opens a Case; a zone that stays isolated
  updates the Case's last_contribution_at; a change of mechanism (stranded ->
  submerged), a reconnection, or a renewed isolation appends a contribution.
  The engine never resolves or closes a Case: that is a human decision.
- Silence: each household's most recent probe as of `now` (older unanswered
  probes are moot once a later one is answered), if still unanswered at
  `now`, judged against the household's own baseline from earlier probes
  (silence_baseline). A late household joins an open isolation
  Case in its zone as a second engine (confidence_word -> corroborated) or
  opens its own household Case; its eventual response is recorded.

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
from app.models.case_engine_contribution import Engine
from app.services import isolation_engine as engine
from app.services import silence_baseline
from app.services.isolation_cases import ENGINE_CONFIDENCE, clear_cases, isolation_mechanism
from app.services.river_driver import SiteContext

log = logging.getLogger(__name__)

CADENCE = timedelta(minutes=15)
# Ordinal tier for a silence flag, not a calibrated probability (no real probe data yet).
SILENCE_CONFIDENCE = 0.5


def replay_source(start: datetime, end: datetime, tz, label: str) -> str:
    """Source label for replayed cases, e.g. backtest:2017-08-25..2017-09-02:USGS-08074500."""
    return f"backtest:{start.astimezone(tz).date()}..{(end - timedelta(seconds=1)).astimezone(tz).date()}:{label}"


def _fmt_s(seconds: float) -> str:
    return f"{seconds:.0f} s" if seconds < 120 else f"{seconds / 60:.0f} min"


@dataclass
class SweepResult:
    now: datetime
    opened: int = 0
    updated: int = 0
    contributions: int = 0


@dataclass
class _Tracked:
    case: Case
    state: str  # last isolation mechanism, or "reconnected"


@dataclass
class CaseSweeper:
    """Opens and updates Cases for one gauge (isolation) and its zones' households (silence)."""

    db: Session
    source: str
    tz: object
    ctx: Optional[SiteContext] = None  # isolation; None for a silence-only sweep
    household_zone_ids: list = field(default_factory=list)
    _zone_cases: dict = field(default_factory=dict)  # zone_id -> _Tracked (isolation cases)
    _household_cases: dict = field(default_factory=dict)  # household_id -> Case (silence-only cases)
    _flagged_probes: dict = field(default_factory=dict)  # probe_id -> Case it contributed to
    _households: dict = field(default_factory=dict)  # household_id -> Household, loaded once at start

    def start(self, replace: bool = True) -> None:
        if replace:
            removed = clear_cases(self.db, self.source)
            self.db.commit()
            if removed:
                log.info("%s: replaced %d existing cases", self.source, removed)
        if self.ctx is not None:
            self.household_zone_ids = [z.id for z in self.ctx.zones]
            self._highway_class = list(self.ctx.segments["highway_class"])
        # The registry does not change during a replay: load the swept households once.
        if self.household_zone_ids:
            self._households = {h.id: h for h in self.db.scalars(
                select(Household).where(Household.zone_id.in_(self.household_zone_ids)))}

    # ---------------------------------------------------------------- isolation
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
                    case = self._open_isolation_case(zone, k, now, i, mech)
                    self._zone_cases[zone.id] = _Tracked(case, mech.state)
                    result.opened += 1
                else:
                    tracked.case.last_contribution_at = now
                    result.updated += 1
                    if tracked.state != current:
                        mech = isolation_mechanism(ctx.net, ctx.bounds, k, level, self._highway_class)
                        verb = "isolated again" if tracked.state == "reconnected" else f"now {mech.state}"
                        self._contribute(tracked.case, Engine.isolation, now,
                                         f"{verb}: {self._fragment(mech, i)}", ENGINE_CONFIDENCE[ctx.river.confidence])
                        tracked.state = mech.state
                        result.contributions += 1
            elif tracked is not None and tracked.state != "reconnected":
                self._contribute(tracked.case, Engine.isolation, now,
                                 f"reconnected: a route to the main road network is open again at stage "
                                 f"{ctx.stage.stage_ft[i]:.2f} ft", ENGINE_CONFIDENCE[ctx.river.confidence])
                tracked.state = "reconnected"
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

    def _open_isolation_case(self, zone: Zone, k: int, now: datetime, i: int, mech) -> Case:
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
        case = Case(
            zone_id=zone.id, status=CaseStatus.open, source=self.source,
            inference_sentence=(f"Street block with {zone.population_count} residents was cut off from the main "
                                f"road network at {when}: {how}, with USGS {ctx.site.site_id} at "
                                f"{ctx.stage.stage_ft[i]:.2f} ft{caveat}."),
            confidence_word=ConfidenceWord.single_source, opened_at=now, last_contribution_at=now,
        )
        case.contributions.append(CaseEngineContribution(
            engine=Engine.isolation, rule_fragment=self._fragment(mech, i),
            engine_confidence=ENGINE_CONFIDENCE[ctx.river.confidence]))
        self.db.add(case)
        return case

    # ---------------------------------------------------------------- silence
    def _silence(self, now: datetime, result: SweepResult) -> None:
        households = self._households
        if not households:
            return
        # Only each household's most recent check-in as of `now` can make it silent now: once a later
        # probe is answered, an older unanswered one is moot.
        latest = self.db.scalars(
            select(ProbeResponse)
            .where(ProbeResponse.household_id.in_(list(households)), ProbeResponse.sent_at <= now)
            .distinct(ProbeResponse.household_id)
            .order_by(ProbeResponse.household_id, ProbeResponse.sent_at.desc())
        ).all()
        pending = [p for p in latest if p.responded_at is None or p.responded_at > now]
        flagged = list(self.db.scalars(select(ProbeResponse).where(ProbeResponse.id.in_(list(self._flagged_probes)))))
        probes = {p.id: p for p in flagged + pending}.values()
        for probe in probes:
            case = self._flagged_probes.get(probe.id)
            if case is not None:
                if probe.responded_at is not None and probe.responded_at <= now:
                    elapsed = (probe.responded_at - probe.sent_at).total_seconds()
                    self._contribute(case, Engine.silence, now,
                                     f"responded: probe {str(probe.id)[:8]} answered after {_fmt_s(elapsed)}",
                                     SILENCE_CONFIDENCE)
                    del self._flagged_probes[probe.id]
                    result.contributions += 1
                continue
            elapsed = (now - probe.sent_at).total_seconds()
            baseline = silence_baseline.household_baseline(self.db, probe.household_id, before=probe.sent_at)
            verdict = silence_baseline.evaluate(baseline, elapsed)
            if verdict.status != "late":
                continue
            household = households[probe.household_id]
            fragment = (f"late: probe {str(probe.id)[:8]} unanswered after {_fmt_s(elapsed)}; this household's "
                        f"median {_fmt_s(baseline.median_seconds)}, late after {_fmt_s(verdict.late_after_seconds)} "
                        f"(z {verdict.z:+.1f}, {baseline.answered} earlier answers)")
            tracked = self._zone_cases.get(household.zone_id)
            if tracked is not None and tracked.state != "reconnected":
                # Matching: a silent household inside a zone the isolation engine already has open.
                case = tracked.case
                case.confidence_word = ConfidenceWord.corroborated
                self._contribute(case, Engine.silence, now, fragment, SILENCE_CONFIDENCE)
            elif household.id in self._household_cases:
                case = self._household_cases[household.id]
                self._contribute(case, Engine.silence, now, fragment, SILENCE_CONFIDENCE)
            else:
                when = probe.sent_at.astimezone(self.tz).strftime("%Y-%m-%d %H:%M %Z")
                case = Case(
                    zone_id=household.zone_id, household_id=household.id, status=CaseStatus.open,
                    source=self.source, confidence_word=ConfidenceWord.single_source,
                    inference_sentence=(f"Household has not answered a check-in sent at {when} after "
                                        f"{_fmt_s(elapsed)}; it usually answers within "
                                        f"{_fmt_s(baseline.median_seconds)}."),
                    opened_at=now, last_contribution_at=now,
                )
                case.contributions.append(CaseEngineContribution(
                    engine=Engine.silence, rule_fragment=fragment, engine_confidence=SILENCE_CONFIDENCE))
                self.db.add(case)
                self._household_cases[household.id] = case
                result.opened += 1
            self._flagged_probes[probe.id] = case
            result.contributions += 1

    def _contribute(self, case: Case, which: Engine, now: datetime, fragment: str, confidence: float) -> None:
        case.contributions.append(CaseEngineContribution(engine=which, rule_fragment=f"[{now.isoformat()}] {fragment}",
                                                         engine_confidence=confidence))
        case.last_contribution_at = now

    # ---------------------------------------------------------------- sweep
    def sweep(self, now: datetime) -> SweepResult:
        result = SweepResult(now)
        if self.ctx is not None:
            self._isolation(now, result)
        self._silence(now, result)
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
