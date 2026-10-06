"""The after-action report: what a run flagged, when, what was done about it and what was not, as of a time.

Everything is read from stored rows (Cases and their evidence, task event histories, the zone-access warnings,
needs and offers) as of `at`; nothing is estimated and no text is written by a model. It is labelled with the run's
mode first, because what a report can claim depends on it: a replay had no responders, a mixed run's responders,
assignments, needs and offers are synthetic or typed in, and a scenario is not a real event.

What it does not say: whether the Cases were right (confidence words are unvalidated heuristics), what happened to
people, or anything about a zone the engines did not assess.
"""
from collections import Counter
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Run, Zone
from app.models.run import RunMode
from app.services import map_state, needs, run_events, safety, supply_access

ENGINE_PREFIX = "engine"

MODE_LABEL = {
    RunMode.replay: "REPLAY of recorded data: a replay has no responders; its tasks show what the engines would have created",
    RunMode.mixed: "MIXED scenario: real recorded flood and isolation results, with SYNTHETIC responders and assignments, and "
                   "needs and offers typed in by people; none of those are real",
    RunMode.scenario: "SYNTHETIC scenario: not a real event",
    RunMode.live: "LIVE run",
}

LIMITS = (
    "Flagged means flagged by the engines from recorded data. Confidence words are unvalidated heuristics, not "
    "calibrated against outcomes.",
    "This report says nothing about what happened to people. It records what the system flagged and what was entered.",
    "Zones the isolation engine did not assess are counted apart and never read as safe or reachable.",
    "Times are on the run's own clock, in UTC.",
)


def _t(x) -> Optional[str]:
    return x.isoformat() if x is not None else None


def _human(actor: str) -> bool:
    return not (actor or "").startswith(ENGINE_PREFIX)


def build(db: Session, run: Run, at: datetime) -> dict:
    summary = map_state.run_summary(db, run)
    cases = map_state.cases(db, run, at)
    items = [(c["zone_id"], t) for c in cases for t in c["tasks"]]
    safety.attach(db, run, at, items)  # each task's zone access and warnings
    zone_names = {str(z.id): z.name for z in db.scalars(select(Zone).where(Zone.id.in_({c["zone_id"] for c in cases})))} \
        if cases else {}
    name = lambda zid: zone_names.get(zid, zid[:8])  # noqa: E731

    tasks = [t for c in cases for t in c["tasks"]]
    flagged_zones = {c["zone_id"] for c in cases}
    access = supply_access.supply_access(db, run, at)
    board = needs.needs_as_of(db, run, at)
    freshness = map_state.freshness(db, run, at)

    # ---- what was flagged
    opened = sorted(cases, key=lambda c: c["opened_at"])
    contributions = [x for c in cases for x in c["contributions"] if x["engine"] == "isolation"]
    first_cut = min((x["first_observed_at"] for x in contributions if x["direction"] == "supports"), default=None)
    first_back = min((x["first_observed_at"] for x in contributions if x["direction"] == "contradicts"), default=None)

    # ---- what was done
    actions = []  # people's (or scripted) task events, oldest first
    for c in cases:
        for t in c["tasks"]:
            for e in t["events"]:
                if _human(e["actor"]):
                    actions.append({"at": _t(e["at"]), "zone": name(c["zone_id"]), "zone_id": c["zone_id"], "task": t["kind"],
                                    "status": e["status"], "actor": e["actor"], "note": e["note"],
                                    "synthetic": "synthetic" in e["actor"] or run.mode in (RunMode.mixed, RunMode.scenario)})
    actions.sort(key=lambda a: a["at"])
    outcomes = Counter(t["status"] for t in tasks)
    warnings = []
    for c in cases:
        for t in c["tasks"]:
            for w in (t.get("safety") or {}).get("warnings", []):
                warnings.append({"code": w["code"], "severity": w["severity"], "text": w["text"], "zone": name(c["zone_id"]),
                                 "zone_id": c["zone_id"], "task": t["kind"]})
    by_code = Counter(w["code"] for w in warnings)

    # ---- the timeline: moments, oldest first
    timeline = []
    if opened:
        timeline.append({"at": _t(opened[0]["opened_at"]), "kind": "first_case",
                         "text": f"First Case flagged: {name(opened[0]['zone_id'])} ({opened[0]['confidence_word']})."})
        last = opened[-1]
        timeline.append({"at": _t(last["opened_at"]), "kind": "last_case",
                         "text": f"Last of the {len(opened)} Cases flagged by this time ({len(flagged_zones)} zones): {name(last['zone_id'])}."})
    if first_cut:
        timeline.append({"at": _t(first_cut), "kind": "first_cut_off", "text": "First zone found cut off by the isolation engine."})
    if first_back:
        timeline.append({"at": _t(first_back), "kind": "first_reconnection", "text": "First reconnection recorded (a route to the main road network open again)."})
    peak = run_events.run_peak(run)
    if peak and peak <= at:
        timeline.append({"at": _t(peak), "kind": "peak", "text": "Every zone the run flags was cut off at once (the recorded peak)."})
    for a in actions:
        who = a["actor"] + (" (synthetic)" if a["synthetic"] and "synthetic" not in a["actor"] else "")
        timeline.append({"at": a["at"], "kind": "task_action", "text": f"{a['zone']}: task {a['task']} -> {a['status']} by {who}. {a['note']}".strip()})
    timeline.sort(key=lambda x: x["at"])

    return {
        "run": {"id": str(run.id), "name": run.name, "mode": run.mode.value, "mode_label": MODE_LABEL[run.mode], "event": summary["event"],
                "window_start": _t(summary["window_start"]), "window_end": _t(summary["window_end"])},
        "as_of": _t(at),
        "summary": {
            "cases": len(cases), "flagged_zones": len(flagged_zones),
            "cases_by_confidence": dict(Counter(c["confidence_word"] for c in cases)),
            "cases_by_status": dict(Counter(c["status"] for c in cases)),
            "tasks": len(tasks), "tasks_by_status": dict(outcomes),
            "tasks_awaiting_verification": sum(1 for t in tasks if t["verify_before_dispatch"] and t["active"]),
            "zones_cut_off": access["counts"]["isolated"], "zones_may_be_cut_off": access["counts"]["possibly_isolated"],
            "zones_not_assessed": access["counts"]["not_evaluated"],
            "actions_taken": len(actions),
        },
        "timeline": timeline,
        "actions": actions,
        "warnings": {"by_code": dict(by_code), "examples": warnings[:10], "total": len(warnings)},
        "needs": {"writable": board["writable"], "summary": board["summary"],
                  "zones": [{"zone": name_ or z, "zone_id": z, "items": v["items"], "pledges": v["pledges"], "access": v["zone_access"]}
                            for z, v in board["zones"].items() for name_ in [v["name"]]]},
        "sources": [{"name": s["name"], "status": s["status"], "last_observed_at": _t(s["last_observed_at"])} for s in freshness["sources"]],
        "cases": [{"zone": name(c["zone_id"]), "zone_id": c["zone_id"], "confidence_word": c["confidence_word"], "status": c["status"],
                   "opened_at": _t(c["opened_at"]), "engines": c["engines"], "sentence": c["inference_sentence"],
                   "task_status": c["tasks"][-1]["status"] if c["tasks"] else None,
                   "zone_access": (c["tasks"][-1].get("safety") or {}).get("zone_access") if c["tasks"] else None} for c in opened],
        "caveats": summary["caveats"],
        "limits": list(LIMITS),
    }


def to_markdown(r: dict) -> str:
    run, s = r["run"], r["summary"]
    L = [f"# After-action report: {run['event'] or run['name']}", "",
         f"**{run['mode_label']}**", "",
         f"- Run: `{run['name']}`", f"- Window: {run['window_start']} to {run['window_end']}",
         f"- As of: {r['as_of']} (the run's clock, UTC)", "", "## What was flagged", "",
         f"- {s['cases']} Cases in {s['flagged_zones']} zones. By confidence: "
         + (", ".join(f"{k} {v}" for k, v in sorted(s["cases_by_confidence"].items())) or "none") + ".",
         f"- Cut off: {s['zones_cut_off']['zones']} zones ({s['zones_cut_off']['population']:,} people recorded in them). "
         f"May be cut off: {s['zones_may_be_cut_off']['zones']:,} zones. Not assessed: {s['zones_not_assessed']['zones']:,} zones.",
         f"- Tasks: {s['tasks']} " + ("(" + ", ".join(f"{k} {v}" for k, v in sorted(s["tasks_by_status"].items())) + ")" if s["tasks"] else "") + ".", "",
         "## Timeline", ""]
    L += [f"- {x['at']}: {x['text']}" for x in r["timeline"]] or ["- Nothing recorded."]
    L += ["", "## What was done", ""]
    if r["actions"]:
        by = Counter(a["status"] for a in r["actions"])
        L += [f"- {len(r['actions'])} actions recorded by people or scripts (listed in the timeline): "
              + ", ".join(f"{k} {v}" for k, v in sorted(by.items())) + ".",
              "- " + ("These are SCRIPTED SYNTHETIC actions, not real responders." if r["run"]["mode"] in ("mixed", "scenario") else "Recorded by the named actors.")]
    else:
        L += ["- No assignments or other actions were recorded."]
    L += ["", "## Warnings", ""]
    w = r["warnings"]
    L += ([f"- {w['total']} warnings on active tasks: " + ", ".join(f"{k} {v}" for k, v in sorted(w["by_code"].items())) + "."]
          + [f"  - {e['zone']}: {e['text']}" for e in w["examples"]]) if w["total"] else ["- None."]
    n = r["needs"]
    L += ["", "## Needs and offers (typed in by people, not measured)", ""]
    if n["summary"]["zones_with_open_needs"]:
        L += [f"- Open needs in {n['summary']['zones_with_open_needs']} zones: "
              + ", ".join(f"{k} {v['remaining']} ({v['pledged']} offered)" for k, v in n["summary"]["by_item"].items()) + "."]
    else:
        L += ["- None entered at this time." if n["writable"] else "- Not available on this run."]
    L += ["", "## Sources at this time", ""] + [f"- {x['name']}: {x['status']}" + (f", last {x['last_observed_at']}" if x["last_observed_at"] else "") for x in r["sources"]]
    L += ["", "## Caveats", ""] + [f"- {c}" for c in r["caveats"]] + [f"- {c}" for c in r["limits"]]
    L += ["", "## Appendix: every Case flagged", ""] + [
        f"- {c['opened_at']} {c['zone']}: {c['confidence_word']}, {c['status']}, engines {', '.join(c['engines']) or 'none'}; "
        f"task {c['task_status'] or 'none'}, access {c['zone_access'] or 'not assessed'}" for c in r["cases"]]
    return "\n".join(L) + "\n"
