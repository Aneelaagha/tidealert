"""Build the mixed scenario: Harvey's real flood and isolation results, with a synthetic responder layer on top.

The flood layer is not copied: the case matcher reruns on the same recorded USGS gauge data as the Harvey replay,
under its own run (mode "mixed") and its own source labels (mixed:<window>:USGS-<site>). It never uses Harvey's
backtest:... labels, because clear_cases deletes Cases by source label across runs.

The synthetic layer: 6 responders ("Synthetic responder N") and scripted assignments, made through the real
task_actions.assign at their run-clock tick, right after that tick's sweep (an action can't be stamped earlier than
a task's latest event, so assigning after the replay finished would be refused). Which tasks are assigned is a
fixed rule over Harvey's real isolation evidence, with ties broken by zone id; nothing is random, so rerunning this
script rebuilds exactly the same state (it clears the mixed run's Cases, tasks and responders first).

  responders 1-3  re-isolation: every Case that is cut off, reconnected, and cut off again with at least 30 minutes
                  reconnected in between (3 Hunting Bayou blocks: reconnected 2017-08-28 02:15, cut off again 03:45).
                  Assigned 15 minutes into the reconnection (02:30): the after-assignment warning should fire from 03:45.
  responder 4     control, already cut off: the first single-isolation Case (cut off once, then reconnected), assigned
                  15 minutes after its isolation began. Expected: "assigned after that", not the after-assignment warning.
  responder 5     control, stays reconnected: the next single-isolation Case, assigned 15 minutes after it reconnected.
                  Expected: no warning.
  responder 6     not assigned.

A reconnection contradicts a Case, so the task rules flag its task "verify before dispatch", and the real assign
refuses a flagged task. For those, the script first records a (scripted, synthetic) clear-verify through the real
task_actions.clear_verify, as an operator would have to.

Needs the Harvey replay (scripts/run_case_matcher.py 08074500 08076000 08075770) for the selection, and the isolation
pipeline caches for each gauge.

Usage (from the repo root):
    .venv/bin/python scripts/mixed_harvey_scenario.py
"""
import logging
import os
import sys
from collections import defaultdict
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Case, Responder, Run  # noqa: E402
from app.models.case_engine_contribution import CaseEngineContribution, ContributionDirection, Engine  # noqa: E402
from app.models.run import RunMode  # noqa: E402
from app.services import task_actions  # noqa: E402
from app.services.case_matcher import CADENCE, CaseSweeper  # noqa: E402
from app.services.river_driver import HARVEY_END, HARVEY_START, load_site_context  # noqa: E402
from app.services.runs import ensure_run  # noqa: E402
from app.services.stage import timesteps, usgs_source_name  # noqa: E402

SITES = ["08074500", "08076000", "08075770"]
WINDOW = "2017-08-25..2017-09-02"
RUN_NAME = f"mixed:harvey-synthetic-responders:{WINDOW}"
DESCRIPTION = "Mixed scenario: Harvey's real flood + synthetic responders"
ACTOR = "script:mixed-scenario (synthetic)"
STEP = CADENCE
MIN_RECONNECTED = timedelta(minutes=30)


def mixed_source(site: str) -> str:
    return f"mixed:{WINDOW}:USGS-{site}"


def plan_assignments(db) -> list[dict]:
    """The scripted assignments, from the Harvey replay's real isolation evidence. Each: zone, source site, when."""
    harvey = db.scalar(select(Run).where(Run.name == f"backtest:{WINDOW}"))
    if harvey is None:
        sys.exit(f"the Harvey replay backtest:{WINDOW} is not in the database: run scripts/run_case_matcher.py first")
    evidence = defaultdict(list)
    for case, c in db.execute(select(Case, CaseEngineContribution).join(CaseEngineContribution)
                              .where(Case.run_id == harvey.id, CaseEngineContribution.engine == Engine.isolation,
                                     CaseEngineContribution.direction.in_([ContributionDirection.supports,
                                                                           ContributionDirection.contradicts]))):
        evidence[case].append(c)
    cases = sorted(evidence, key=lambda case: str(case.zone_id))
    plan = []
    for case in cases:  # re-isolations
        cs = sorted(evidence[case], key=lambda c: c.first_observed_at)
        for prev, nxt in zip(cs, cs[1:]):
            if prev.direction == ContributionDirection.contradicts and nxt.direction == ContributionDirection.supports \
                    and nxt.first_observed_at - prev.first_observed_at >= MIN_RECONNECTED:
                plan.append({"role": "re-isolation", "zone_id": case.zone_id, "site": case.source.rsplit("-", 1)[-1],
                             "at": prev.first_observed_at + STEP, "expect": "isolated_after_assignment",
                             "from": nxt.first_observed_at})
    single = [case for case in cases
              if "".join(c.direction.value[0] for c in sorted(evidence[case], key=lambda c: c.first_observed_at)) == "sc"]
    a, b = single[0], single[1]
    ca = sorted(evidence[a], key=lambda c: c.first_observed_at)
    cb = sorted(evidence[b], key=lambda c: c.first_observed_at)
    plan.append({"role": "control: already cut off", "zone_id": a.zone_id, "site": a.source.rsplit("-", 1)[-1],
                 "at": ca[0].first_observed_at + STEP, "expect": "zone_isolated (assigned after that)",
                 "from": ca[0].first_observed_at + STEP})
    plan.append({"role": "control: stays reconnected", "zone_id": b.zone_id, "site": b.source.rsplit("-", 1)[-1],
                 "at": cb[1].first_observed_at + STEP, "expect": "no warning", "from": cb[1].first_observed_at + STEP})
    return plan


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    ticks = timesteps(HARVEY_START, HARVEY_END, STEP)
    with SessionLocal() as db:
        db.expire_on_commit = False
        plan = plan_assignments(db)
        run = ensure_run(db, name=RUN_NAME, mode=RunMode.mixed, description=DESCRIPTION,
                         window_start=HARVEY_START, window_end=HARVEY_END,
                         source_names=[usgs_source_name(s) for s in SITES])
        sweepers = []
        for site in SITES:
            ctx = load_site_context(db, site, HARVEY_START, HARVEY_END, STEP)
            if ctx.times != ticks:
                sys.exit(f"USGS {site}: context timesteps do not match the replay ticks")
            sweepers.append(CaseSweeper(db=db, source=mixed_source(site), tz=ctx.tz, ctx=ctx, run_id=run.id))
        for sweeper in sweepers:
            sweeper.start()  # clears this source's previous Cases and tasks: the rerun starts clean
        for old in db.scalars(select(Responder).where(Responder.run_id == run.id)):
            db.delete(old)
        db.flush()
        responders = [Responder(run_id=run.id, name=f"Synthetic responder {i}", role="synthetic responder (mixed scenario)",
                                team_id="synthetic") for i in range(1, 7)]
        db.add_all(responders)
        db.commit()

        if len(plan) > len(responders) - 1:
            sys.exit(f"{len(plan)} scripted assignments for {len(responders)} responders: the rule picked more than planned")
        by_tick = defaultdict(list)
        for i, p in enumerate(plan):
            by_tick[p["at"]].append((responders[i], p))
        made = []
        for now in ticks:
            for sweeper in sweepers:
                sweeper.sweep(now)
            for responder, p in by_tick.get(now, []):
                case = db.scalar(select(Case).where(Case.run_id == run.id, Case.zone_id == p["zone_id"],
                                                    Case.source == mixed_source(p["site"])))
                task = next((t for t in case.tasks if t.status.value in ("pending",)), None) if case else None
                if task is None:
                    sys.exit(f"{p['role']}: no pending task for zone {p['zone_id']} at {now}")
                if task.verify_before_dispatch:
                    # A reconnection contradicts the Case, so the rules flag the task; the real assign refuses a
                    # flagged task. As an operator would have to, a (scripted, synthetic) person clears it first.
                    task_actions.clear_verify(db, task, ACTOR, at=now,
                                              note="scripted: reviewed the contradicting evidence; dispatch anyway")
                    p["cleared_verify"] = True
                task_actions.assign(db, task, responder, ACTOR, at=now,
                                    note=f"scripted ({p['role']}); expected: {p['expect']}")
                db.commit()
                made.append((responder.name, p, task.id))

    print(f"{RUN_NAME}: swept {len(ticks)} ticks of {', '.join(SITES)}; {len(made)} scripted assignments")
    for name, p, task_id in made:
        print(f"  {name}: {p['role']} — zone {p['zone_id']} (USGS-{p['site']}) assigned at {p['at']:%Y-%m-%d %H:%M} UTC; "
              f"expected {p['expect']} from {p['from']:%Y-%m-%d %H:%M} UTC (task {task_id})"
              + ("; verify flag cleared first" if p.get("cleared_verify") else ""))


if __name__ == "__main__":
    main()
