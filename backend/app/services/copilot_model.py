"""Copilot model mode: an LLM chooses tools and writes the answer; the server states every value.

The model sees tool results (so it can decide what matters) but may not write
any of their values. It writes placeholders like {{t1.risk_level}} that the
server fills from the tool result with that id, the same values the templates
use. Before filling, the server rejects the answer if its own text (outside
placeholders) contains:
- a status word (STATUS_WORDS: risk levels, confidence words, Case and task
  statuses, task priorities, source freshness, household statuses), in either
  the stored form (stale_verify) or with spaces (stale verify);
- a digit (counts, confidences, times and populations must come through
  placeholders);
- a copy of any non-vocabulary string value from a tool result of 8 or more
  characters (zone names, inference sentences, rules);
- a placeholder that names no tool result or no scalar value in it, or stray
  braces.
A rejected answer is never shown. The model is told why and rewrites it once
(MAX_REWRITES); the rewrite goes through the same check, and if it fails too the
copilot falls back to template mode and says why. So does a refusal, an API error, a turn limit, and any tool result
that touches a real household (ToolResult.external_ok is false), which is
never sent to the model.

Tools take no arguments: the zone and Case are the ones selected on the map,
so the model can't reach beyond the selection.

Limits (every one falls back to templates, never to an unchecked answer):
- per client IP: RATE_LIMIT model questions per RATE_WINDOW_SECONDS
  (in-process; template answers are not counted or limited);
- per question: TOKEN_CAP input + output tokens summed over the model's turns,
  checked at each turn boundary (so one turn's input can overrun it), and each
  turn's max_tokens is cut to what is left;
- per question: MAX_TOOL_CALLS tool calls, and MAX_ROUNDS model turns.
"""
import importlib.util
import json
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from app.models.case import CaseStatus, ConfidenceWord
from app.models.case_engine_contribution import ContributionDirection, Engine
from app.models.household import HouseholdStatus
from app.models.task import TaskPriority, TaskStatus
from app.models.zone import RiskLevel
from app.services import copilot_tools as tools

MODEL = "claude-opus-5-5"
EFFORT = "medium"
MAX_TOKENS = 16000
MAX_ROUNDS = 6  # model turns per question (each may call several tools)
MAX_TOOL_CALLS = 8  # tool calls per question, over all turns
MAX_REWRITES = 1  # a rejected answer gets this many rewrites (each checked the same way) before falling back
TOKEN_CAP = 60000  # input + output tokens per question, over all turns
MIN_TURN_TOKENS = 2048  # don't start a turn with less output room than this
RATE_LIMIT = 20  # model questions per client IP ...
RATE_WINDOW_SECONDS = 600  # ... per this many seconds
TIMEOUT_SECONDS = 60
FALLBACK_BETA = "server-side-fallback-2026-07-01"  # on a refusal the API reruns the request on a fallback model
OUT_OF_SCOPE_TOKEN = "OUT_OF_SCOPE"
NOT_ASSESSED = "not assessed"

FRESHNESS = ("fresh", "stale", "no_data", "event_driven")  # app.services.map_state.freshness statuses
STATUS_WORDS = sorted({v.value for e in (RiskLevel, ConfidenceWord, CaseStatus, TaskStatus, TaskPriority,
                                         HouseholdStatus) for v in e} | set(FRESHNESS))
# "open Case(s)" names a kind of question (the open_cases intent), not a Case's status.
ALLOWED_PHRASES = (re.compile(r"\bopen cases?\b", re.I),)
_STATUS_RE = re.compile(r"\b(" + "|".join(re.escape(w).replace("_", "[_ ]") for w in
                                          sorted(STATUS_WORDS, key=len, reverse=True)) + r")\b", re.I)
_VOCAB = set(STATUS_WORDS) | {v.value for e in (Engine, ContributionDirection) for v in e}
PLACEHOLDER = re.compile(r"\{\{\s*(t\d+)((?:\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])+)\s*\}\}")
_PATH_PART = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")
MIN_COPIED = 8

# The five grounded tools, as the model sees them; each maps to its template intent.
TOOL_INTENTS = {"zone_status": "zone_status", "zone_cases": "zone_cases", "open_cases": "open_cases",
                "explain_confidence": "explain_confidence", "briefing_facts": "briefing"}
_TOOL_DESCRIPTIONS = {
    "zone_status": "The selected zone as of the map's time: risk level (and why it isn't assessed), data "
                   "confidence, coverage gaps, Case and task summaries. Needs a selected zone.",
    "zone_cases": "Every Case in the selected zone opened by the map's time, with contributions and tasks. "
                  "Needs a selected zone.",
    "open_cases": "The run's Cases not yet closed as of the map's time, strongest confidence first.",
    "explain_confidence": "Why the selected Case has its confidence word: the rule that decided it and each "
                          "contribution's stored and decayed confidence. Needs a selected Case.",
    "briefing_facts": "Everything a draft responder briefing for the selected zone may state: zone status, its "
                      "Cases with latest evidence, tasks, source freshness. Needs a selected zone.",
}
TOOLS = [{"name": name, "description": desc, "strict": True,
          "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}}
         for name, desc in _TOOL_DESCRIPTIONS.items()]

SYSTEM = f"""You answer questions about one flood-response run, using only the tools given. The tools read the \
selected zone and Case on the map; they take no arguments.

Every fact in your answer must be a placeholder that the server fills from a tool result. Each tool result has \
an id (t1, t2, ...) and its data; write {{{{<id>.<path>}}}} for a value, e.g. {{{{t1.risk_level}}}}, \
{{{{t1.cases[0].confidence_word}}}}, {{{{t2.contributions[1].effective_confidence}}}}. A path must end at a \
single value or a list of plain values. A null value is filled as "{NOT_ASSESSED}".

Your own words must never contain: any digit; any of these words, with or without underscores: \
{", ".join(STATUS_WORDS)}; or any text copied from a tool result (names, sentences, rules). Write those only as \
placeholders. An answer that breaks this is discarded. Refer to listed Cases as "these Cases" or "the Cases \
listed", not by their status, and don't repeat a status word from the question, even to say you can't judge it. The server adds the time and run to the start of every \
answer, so don't state them.

Answer only: {{intents}}. If the question asks for anything else, or needs outside knowledge, reply with exactly \
{OUT_OF_SCOPE_TOKEN} and call no tool. If a tool says a selection is missing, tell the user what to select. \
State gaps plainly (a value filled as "{NOT_ASSESSED}", no Case) and never guess. Keep answers short and plain."""


class Rejected(ValueError):
    pass


class Fallback(Exception):
    """The model path can't answer; the copilot falls back to templates for `intent` (None: route the question)."""

    def __init__(self, reason: str, intent: Optional[str] = None):
        super().__init__(reason)
        self.reason, self.intent = reason, intent


# ---------------------------------------------------------------- placeholders and the rejection check
def _resolve(data: Any, path: str) -> Any:
    value = data
    for key, index in _PATH_PART.findall(path):
        if key:
            if not isinstance(value, dict) or key not in value:
                raise Rejected(f"placeholder path {path!r} names no value")
            value = value[key]
        else:
            if not isinstance(value, list) or int(index) >= len(value):
                raise Rejected(f"placeholder path {path!r} names no value")
            value = value[int(index)]
    if isinstance(value, dict) or (isinstance(value, list) and any(isinstance(v, (dict, list)) for v in value)):
        raise Rejected(f"placeholder path {path!r} names a group of values, not one value")
    return value


def format_value(value: Any) -> str:
    if value is None:
        return NOT_ASSESSED
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M UTC")
    if isinstance(value, list):
        return ", ".join(format_value(v) for v in value) if value else "none"
    return str(value)


def _strings(data: Any):
    if isinstance(data, dict):
        for v in data.values():
            yield from _strings(v)
    elif isinstance(data, list):
        for v in data:
            yield from _strings(v)
    elif isinstance(data, str):
        yield data


def check(text: str, results: dict[str, dict]) -> None:
    """Raise Rejected if the model's own words (outside placeholders) state a value. `results`: id -> data."""
    for rid, path in PLACEHOLDER.findall(text):
        if rid not in results:
            raise Rejected(f"placeholder names no tool result: {rid}")
        _resolve(results[rid], path)
    own = PLACEHOLDER.sub(" ", text)
    if "{" in own or "}" in own:
        raise Rejected("malformed placeholder")
    scrubbed = own
    for phrase in ALLOWED_PHRASES:
        scrubbed = phrase.sub(" ", scrubbed)
    m = _STATUS_RE.search(scrubbed)
    if m:
        raise Rejected(f"status word written outside a placeholder: {m.group(0)!r}")
    m = re.search(r"\d+", own)
    if m:
        raise Rejected(f"number written outside a placeholder: {m.group(0)!r}")
    lowered = own.lower()
    for data in results.values():
        for s in _strings(data):
            if len(s) >= MIN_COPIED and s not in _VOCAB and s.lower() in lowered:
                raise Rejected(f"tool text copied outside a placeholder: {s[:40]!r}")


def fill(text: str, results: dict[str, dict]) -> tuple[str, list[str]]:
    """Substitute every placeholder; return the text and the paths that were null (stated as not assessed)."""
    nulls = []

    def sub(m):
        value = _resolve(results[m.group(1)], m.group(2))
        if value is None:
            nulls.append(m.group(1) + m.group(2))
        return format_value(value)

    return PLACEHOLDER.sub(sub, text), nulls


# ---------------------------------------------------------------- rate limit
class RateLimiter:
    """At most `limit` admissions per key in any `window` seconds (a sliding window, in process memory)."""

    def __init__(self, limit: int, window: float):
        self.limit, self.window = limit, window
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def admit(self, key: str, now: Optional[float] = None) -> Optional[int]:
        """Record an admission and return None, or return the seconds until the key may try again."""
        now = time.monotonic() if now is None else now
        with self._lock:
            for k in [k for k, q in self._hits.items() if not q or q[-1] <= now - self.window]:
                del self._hits[k]  # keys idle for a whole window
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(1, int(hits[0] + self.window - now + 0.999))
            hits.append(now)
            return None


LIMITER = RateLimiter(RATE_LIMIT, RATE_WINDOW_SECONDS)


# ---------------------------------------------------------------- the model loop
@dataclass
class Context:
    """What the tools may read: the run, the map's time and the selection. Nothing else reaches the model."""
    db: Any
    run_id: Any
    at: Optional[datetime]
    zone_id: Any = None
    case_id: Any = None


@dataclass
class ModelAnswer:
    text: str  # filled
    results: list  # ToolResults, in call order
    nulls: list = field(default_factory=list)
    placeholders: int = 0
    out_of_scope: bool = False
    served_by: Optional[str] = None
    rewrites: int = 0  # how many times the answer was rejected and rewritten before it passed


def api_key_set() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def sdk_available() -> bool:
    return importlib.util.find_spec("anthropic") is not None


def make_client():
    import anthropic
    return anthropic.Anthropic(timeout=TIMEOUT_SECONDS)


def _payload(rid: str, result: tools.ToolResult) -> str:
    return json.dumps({"result_id": rid, "data": result.data}, default=format_value, sort_keys=True)


def run(ctx: Context, question: str, call_tool: Callable[[str], tools.ToolResult], client=None,
        intents: str = "") -> ModelAnswer:
    """Ask the model; execute its tool calls through `call_tool`; check and fill its answer.
    Raises Fallback on anything that keeps it from giving a checked answer."""
    import anthropic

    client = client or make_client()
    selection = (f"Selected zone: {'yes' if ctx.zone_id else 'none'}. "
                 f"Selected Case: {'yes' if ctx.case_id else 'none'}.")
    messages = [{"role": "user", "content": f"{selection}\n\nQuestion: {question}"}]
    results: dict[str, tools.ToolResult] = {}
    first_intent, used_tokens, tool_calls, rewrites = None, 0, 0, 0
    for _ in range(MAX_ROUNDS):
        room = min(MAX_TOKENS, TOKEN_CAP - used_tokens)
        if room < MIN_TURN_TOKENS:
            raise Fallback(f"token cap reached ({used_tokens} of {TOKEN_CAP} tokens used)", first_intent)
        try:
            response = client.beta.messages.create(
                model=MODEL, max_tokens=room, system=SYSTEM.replace("{intents}", intents),
                tools=TOOLS, messages=messages, output_config={"effort": EFFORT},
                betas=[FALLBACK_BETA], fallbacks="default")
        except anthropic.APIStatusError as exc:
            raise Fallback(f"model API error (HTTP {exc.status_code})", first_intent)
        except anthropic.APIConnectionError:
            raise Fallback("model API unreachable", first_intent)
        usage = getattr(response, "usage", None)
        if usage is not None:
            used_tokens += (usage.input_tokens or 0) + (usage.output_tokens or 0) \
                + (getattr(usage, "cache_read_input_tokens", 0) or 0) \
                + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        if response.stop_reason == "refusal":
            raise Fallback("the model declined to answer", first_intent)
        if response.stop_reason == "max_tokens":
            raise Fallback("the model's answer was cut off", first_intent)
        messages.append({"role": "assistant", "content": response.content})  # unchanged: thinking blocks too
        uses = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason != "tool_use" or not uses:
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            if results and text and text != OUT_OF_SCOPE_TOKEN and rewrites < MAX_REWRITES:
                try:
                    check(text, {rid: r.data for rid, r in results.items()})
                except Rejected as exc:
                    # Not shown. The model is told why and rewrites once; the rewrite goes through the same check
                    # in _finish, so nothing it writes is shown unchecked.
                    rewrites += 1
                    messages.append({"role": "user", "content": f"Your answer was discarded: {exc}. Rewrite it with "
                                     "every such value as a placeholder and nothing else changed."})
                    continue
            return _finish(text, results, first_intent, getattr(response, "model", None), rewrites)
        tool_calls += len(uses)
        if tool_calls > MAX_TOOL_CALLS:
            raise Fallback(f"tool-call cap reached (the model asked for {tool_calls}; the cap is "
                           f"{MAX_TOOL_CALLS})", first_intent or TOOL_INTENTS.get(uses[0].name))
        replies = []
        for use in uses:
            if use.name not in TOOL_INTENTS:
                replies.append({"type": "tool_result", "tool_use_id": use.id, "is_error": True,
                                "content": f"no tool named {use.name}"})
                continue
            first_intent = first_intent or TOOL_INTENTS[use.name]
            try:
                result = call_tool(use.name)
            except ValueError as exc:  # a missing selection (copilot.CopilotInputError)
                replies.append({"type": "tool_result", "tool_use_id": use.id, "is_error": True,
                                "content": str(exc)})
                continue
            if not result.external_ok:
                raise Fallback(f"{use.name} touches {len(result.real_household_ids)} real household(s); "
                               "real household data is never sent to an external model", TOOL_INTENTS[use.name])
            rid = f"t{len(results) + 1}"
            results[rid] = result
            replies.append({"type": "tool_result", "tool_use_id": use.id, "content": _payload(rid, result)})
        messages.append({"role": "user", "content": replies})
    raise Fallback(f"the model did not finish within {MAX_ROUNDS} turns", first_intent)


def _finish(text: str, results: dict, first_intent, served_by, rewrites: int = 0) -> ModelAnswer:
    if text == OUT_OF_SCOPE_TOKEN and not results:
        return ModelAnswer(text="", results=[], out_of_scope=True, served_by=served_by)
    if not results:
        raise Fallback("the model answered without reading any tool", first_intent)
    if not text:
        raise Fallback("the model returned no answer", first_intent)
    data = {rid: r.data for rid, r in results.items()}
    try:
        check(text, data)
    except Rejected as exc:
        raise Fallback(f"model answer rejected{' after a rewrite' if rewrites else ''}: {exc}", first_intent)
    filled, nulls = fill(text, data)
    return ModelAnswer(text=filled, results=list(results.values()), nulls=nulls,
                       placeholders=len(PLACEHOLDER.findall(text)), served_by=served_by, rewrites=rewrites)
