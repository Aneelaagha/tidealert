"""Copilot: answers questions about a run as of a time, from the database only.

Scope (no spec wording exists beyond "AI copilot"; scoped with the project
owner): zone status, a zone's Cases, the open Cases, why a Case has its
confidence word, and a responder briefing for a zone. Anything else gets a
fixed out-of-scope reply, never an answer from general knowledge.

Modes:
- template: answers built entirely from tool results (app.services.copilot_tools)
  by fixed templates. The automatic mode when ANTHROPIC_API_KEY is not set, and
  the only mode until the model path is built (PR 2).
- model (PR 2): an LLM chooses tools and writes the answer with placeholders
  that the server fills from tool results.

Gaps are stated, never filled: a null value reads "not assessed", a zone with
no Case says so, an unknown risk level gives the stored reason.
"""
import os
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.services import copilot_tools as tools

INTENTS = {
    "zone_status": "the status of the selected zone",
    "zone_cases": "the Cases in the selected zone",
    "open_cases": "a summary of the run's open Cases",
    "explain_confidence": "why the selected Case has its confidence word",
    "briefing": "a draft responder briefing for the selected zone",
}
OUT_OF_SCOPE = ("I can only answer from this run's data: " + "; ".join(INTENTS.values())
                + ". I don't answer other questions or use outside knowledge.")
# Keyword routing for free text in template mode (a model routes free text in model mode).
KEYWORDS = [("explain_confidence", ("why", "confidence", "corroborated", "single_source", "stale")),
            ("briefing", ("brief",)),
            ("open_cases", ("open cases", "all cases", "summar", "overview")),
            ("zone_cases", ("cases in", "zone's cases", "which cases")),
            ("zone_status", ("status", "what's happening", "what is happening", "how is"))]


def model_status() -> dict:
    if not os.getenv("ANTHROPIC_API_KEY"):
        return {"mode": "template", "reason": "ANTHROPIC_API_KEY is not set: answers come from fixed templates"}
    return {"mode": "template", "reason": "model-backed answers are not built yet (PR 2): fixed templates"}


def route(question: str, intent: Optional[str]) -> Optional[str]:
    if intent:
        return intent if intent in INTENTS else None
    q = (question or "").lower()
    for name, words in KEYWORDS:
        if any(w in q for w in words):
            return name
    return None


def _when(r: tools.ToolResult) -> str:
    return f"As of {r.at.strftime('%Y-%m-%d %H:%M UTC')} ({r.run['mode'].upper()} run)"


def _time(t) -> str:
    return t.strftime("%Y-%m-%d %H:%M UTC") if isinstance(t, datetime) else str(t)


def _latest(case: dict) -> Optional[dict]:
    evidence = [c for c in case["contributions"] if c["direction"] in ("supports", "contradicts")]
    return max(evidence, key=lambda c: c["last_confirmed_at"]) if evidence else None


def _fragment(c: dict) -> str:
    return c["rule_fragment"].split("] ", 1)[-1]


# ---------------------------------------------------------------- templates
def _zone_status_text(r: tools.ToolResult) -> tuple[str, list[str]]:
    z, unknowns = r.data, []
    risk = z["risk_level"]
    if risk == "unknown":
        unknowns.append("risk level")
    lines = [f"{_when(r)}: {z['name']} ({z['region']}), population {z['population']}.",
             f"Risk level: {risk}" + (f" ({z['risk_level_note']})" if z["risk_level_note"] else
                                      " (not assessed by any engine)" if risk == "unknown" else "") + "."]
    if z["data_confidence"] is None:
        unknowns.append("data confidence")
        lines.append("Data confidence: not assessed.")
    else:
        lines.append(f"Data confidence: {z['data_confidence']}.")
    if z["case_count"]:
        lines.append(f"Cases: {z['case_count']}, strongest confidence word {z['confidence_word']}; "
                     f"engines with supporting evidence: {', '.join(z['engines']) or 'none'}.")
    else:
        unknowns.append("Case")
        lines.append("Cases: none as of this time.")
    if z["task_count"]:
        lines.append(f"Active tasks: {z['task_count']} (most advanced: {z['task_status']}; "
                     f"{z['task_awaiting']} awaiting assignment, {z['task_flagged']} flagged verify before dispatch).")
    else:
        lines.append("Active tasks: none.")
    for g in z["coverage_gaps"]:
        when = "active" if g["active"] else f"not yet active (from {g['since']})"
        lines.append(f"Coverage gap ({g['kind']}{', ' + g['status'] if g['status'] else ''}, {when}): {g['reason']}")
    return "\n".join(lines), unknowns


def _case_lines(case: dict) -> list[str]:
    lines = [f"- {case['confidence_word']} · {case['status']} · opened {_time(case['opened_at'])}: "
             f"{case['inference_sentence']}"]
    latest = _latest(case)
    if latest:
        lines.append(f"  Latest evidence ({latest['engine']}, {latest['direction']}, last confirmed "
                     f"{_time(latest['last_confirmed_at'])}): {_fragment(latest)}")
    for t in case["tasks"]:
        flag = "; flagged verify before dispatch" if t["verify_before_dispatch"] else ""
        lines.append(f"  Task ({t['kind']}): {t['status']}, priority {t['priority']}{flag}. "
                     f"Last note: {t['events'][-1]['note']}")
    return lines


def _zone_cases_text(r: tools.ToolResult) -> tuple[str, list[str]]:
    cases = r.data["cases"]
    if not cases:
        return f"{_when(r)}: no Case in this zone.", ["Case"]
    lines = [f"{_when(r)}: {len(cases)} Case(s) in this zone."]
    for c in cases:
        lines += _case_lines(c)
    return "\n".join(lines), []


def _open_cases_text(r: tools.ToolResult) -> tuple[str, list[str]]:
    d = r.data
    if not d["total"]:
        return f"{_when(r)}: no open Cases.", ["Case"]
    counts = {}
    for c in d["cases"]:
        counts[c["confidence_word"]] = counts.get(c["confidence_word"], 0) + 1
    lines = [f"{_when(r)}: {d['total']} open Case(s)" + (f"; the first {d['shown']} by confidence:" if d["shown"] < d["total"] else ":")]
    for c in d["cases"][:10]:
        kind = "household" if c["household_case"] else "zone"
        lines.append(f"- {c['confidence_word']} · {c['status']} · {kind} Case opened {_time(c['opened_at'])} "
                     f"({', '.join(c['engines']) or 'no supporting engine'}): {c['inference_sentence']}")
    if d["total"] > 10:
        lines.append(f"... and {d['total'] - 10} more.")
    return "\n".join(lines), []


def _explain_text(r: tools.ToolResult) -> tuple[str, list[str]]:
    d = r.data
    lines = [f"{_when(r)}: this Case reads {d['confidence_word']}.", f"Rule: {d['rule']}.",
             f"Combined support {d['support']}, against {d['contradiction']}, fresh sources {d['fresh_sources']} "
             f"(a supporting contribution is fresh while its decayed confidence is at least {d['fresh_threshold']}; "
             "half-lives in minutes: " + ", ".join(f"{k} {v}" for k, v in d["half_lives_minutes"].items()) + ")."]
    for c in d["contributions"]:
        fresh = " (fresh)" if c["fresh"] else ""
        lines.append(f"- {c['engine']} {c['direction']}: confidence {c['stored_confidence']} when last confirmed "
                     f"({_time(c['last_confirmed_at'])}), {c['effective_confidence']} at this time after decay{fresh}. "
                     f"Recorded when first observed: {c['fragment']}")
    lines.append("(The recorded text is written when evidence is first observed; evidence the engine keeps "
                 "re-confirming has its confidence updated since, so the two can differ.)")
    lines.append(d["caveat"])
    return "\n".join(lines), []


def _briefing_text(r: tools.ToolResult) -> tuple[str, list[str]]:
    d = r.data
    zone_result = tools.ToolResult("zone_status", r.run, r.at, d["zone"])
    status, unknowns = _zone_status_text(zone_result)
    lines = ["DRAFT RESPONDER BRIEFING. Generated from database state; verify before use.", "", status, ""]
    if d["cases"]:
        lines.append("Cases and latest evidence:")
        for c in d["cases"]:
            lines += _case_lines(c)
    else:
        lines.append("No Case in this zone: nothing here asks for a response as of this time.")
    lines.append("")
    srcs = d["freshness"]["sources"]
    if srcs:
        lines.append("Data sources: " + "; ".join(f"{s['name']}: {s['status'].replace('_', ' ')}" for s in srcs) + ".")
    elif d["freshness"]["note"]:
        lines.append(d["freshness"]["note"])
    lines += r.run["caveats"]
    return "\n".join(lines), unknowns


TEMPLATES = {"zone_status": _zone_status_text, "zone_cases": _zone_cases_text, "open_cases": _open_cases_text,
             "explain_confidence": _explain_text, "briefing": _briefing_text}


# ---------------------------------------------------------------- answer
class CopilotInputError(ValueError):
    pass


def _call(db: Session, intent: str, run_id, at, zone_id, case_id) -> tools.ToolResult:
    needs = {"zone_status": "zone_id", "zone_cases": "zone_id", "briefing": "zone_id", "explain_confidence": "case_id"}
    need = needs.get(intent)
    if need == "zone_id" and zone_id is None:
        raise CopilotInputError(f"{INTENTS[intent]} needs a zone: select one on the map")
    if need == "case_id" and case_id is None:
        raise CopilotInputError(f"{INTENTS[intent]} needs a Case: pick one in the zone panel")
    if intent == "zone_status":
        return tools.zone_status(db, run_id, zone_id, at)
    if intent == "zone_cases":
        return tools.zone_cases(db, run_id, zone_id, at)
    if intent == "open_cases":
        return tools.open_cases(db, run_id, at)
    if intent == "explain_confidence":
        return tools.explain_confidence(db, run_id, case_id, at)
    return tools.briefing_facts(db, run_id, zone_id, at)


def ask(db: Session, run_id, question: str = "", intent: Optional[str] = None, at: Optional[datetime] = None,
        zone_id=None, case_id=None) -> dict:
    status = model_status()
    chosen = route(question, intent)
    base = {"mode": status["mode"], "mode_reason": status["reason"], "question": question, "intent": chosen}
    if chosen is None:
        return {**base, "answer": OUT_OF_SCOPE, "in_scope": False, "unknowns": [], "tools": []}
    result = _call(db, chosen, run_id, at, zone_id, case_id)
    text, unknowns = TEMPLATES[chosen](result)
    return {**base, "in_scope": True, "answer": text, "unknowns": unknowns, "as_of": result.at,
            "run": {k: result.run[k] for k in ("id", "name", "mode")}, "tools": [result.tool],
            "household_data": {"households": len(result.household_ids), "real": len(result.real_household_ids),
                               "may_send_to_external_model": result.external_ok}}
