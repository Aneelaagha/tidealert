"""Copilot model mode without a real model: the rejection check, placeholder filling, the tool-calling loop
(driven by a scripted fake client), and every fallback to templates. No request leaves the machine; the
endpoint tests need the same local database as tests/test_copilot.py."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app.main import app
from app.models import Household
from app.models.household import AgeBracket
from app.services import copilot
from app.services import copilot_model as model
from app.services.copilot_tools import ToolResult

PEAK = "2017-08-27T18:30:00Z"
AT = datetime(2017, 8, 27, 18, 30, tzinfo=timezone.utc)
RUN = {"id": "r", "name": "run", "mode": "replay", "caveats": []}


# ---------------------------------------------------------------- a scripted stand-in for the API
def text(t):
    return SimpleNamespace(type="text", text=t)


def tool_use(name, id_="tu1"):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input={})


def reply(*blocks, stop="end_turn", tokens=None):
    usage = None if tokens is None else SimpleNamespace(input_tokens=tokens, output_tokens=0)
    return SimpleNamespace(stop_reason=stop, content=list(blocks), model=model.MODEL, usage=usage)


@pytest.fixture(autouse=True)
def fresh_limiter(monkeypatch):
    monkeypatch.setattr(model, "LIMITER", model.RateLimiter(model.RATE_LIMIT, model.RATE_WINDOW_SECONDS))


class FakeClient:
    """Answers each create() with the next scripted step: a response, or a function of the request."""

    def __init__(self, *steps):
        self.steps, self.requests = list(steps), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.requests.append({**kw, "messages": list(kw["messages"])})
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step(kw) if callable(step) else step

    def tool_payloads(self):
        return [json.loads(b["content"]) for r in self.requests for m in r["messages"] if m["role"] == "user"
                and isinstance(m["content"], list) for b in m["content"] if not b.get("is_error")]


def result(data, real=()):
    return ToolResult("zone_status", RUN, AT, data, set(real), set(real))


ZONE = {"name": "White Oak block G", "risk_level": "extreme", "data_confidence": None, "case_count": 2,
        "engines": ["isolation", "silence"], "confidence_word": "stale_verify",
        "cases": [{"confidence_word": "corroborated", "opened_at": AT}]}
CTX = model.Context(db=None, run_id="r", at=AT, zone_id="z")


# ---------------------------------------------------------------- the rejection check
def test_the_status_vocabulary_comes_from_the_enums():
    for w in ("extreme", "elevated", "unknown", "safe", "corroborated", "single_source", "stale_verify",
              "pending", "en_route", "in_progress", "resolved", "stale", "fresh", "needs_help"):
        assert w in model.STATUS_WORDS


@pytest.mark.parametrize("answer", [
    "The zone is extreme.", "This Case is Stale_Verify.", "it reads stale verify", "single source only",
    "a task is pending", "the area is safe", "the risk is unknown", "the data is stale",
])
def test_status_words_outside_placeholders_are_rejected(answer):
    with pytest.raises(model.Rejected, match="status word"):
        model.check(answer, {"t1": ZONE})


@pytest.mark.parametrize("answer, why", [
    ("There are 2 Cases.", "number"),
    ("{{t1.name}} is near White Oak block G.", "copied"),
    ("Risk: {{t2.risk_level}}.", "no tool result"),
    ("Risk: {{t1.risk}}.", "names no value"),
    ("Cases: {{t1.cases[5].confidence_word}}.", "names no value"),
    ("Everything: {{t1.cases}}.", "group of values"),
    ("Risk: {t1.risk_level}.", "malformed"),
])
def test_values_written_by_the_model_are_rejected(answer, why):
    with pytest.raises(model.Rejected, match=why):
        model.check(answer, {"t1": ZONE})


def test_placeholders_and_plain_words_pass():
    model.check("In {{t1.name}} the risk level reads {{t1.risk_level}}; the open Cases read "
                "{{t1.cases[0].confidence_word}}. Engines: {{t1.engines}}. The listening engine agrees.",
                {"t1": ZONE})


def test_fill_states_every_value_from_the_tool_result():
    filled, nulls = model.fill("{{t1.name}}: {{t1.risk_level}}; confidence {{t1.data_confidence}}; "
                               "{{t1.case_count}} Cases from {{t1.engines}}; opened {{t1.cases[0].opened_at}}.",
                               {"t1": ZONE})
    assert filled == ("White Oak block G: extreme; confidence not assessed; 2 Cases from isolation, silence; "
                      "opened 2017-08-27 18:30 UTC.")
    assert nulls == ["t1.data_confidence"]


# ---------------------------------------------------------------- tool-calling structure
def test_the_model_gets_exactly_the_five_grounded_tools_without_arguments():
    assert [t["name"] for t in model.TOOLS] == ["zone_status", "zone_cases", "open_cases", "explain_confidence",
                                                "briefing_facts"]
    for t in model.TOOLS:
        assert t["strict"] is True and t["input_schema"] == {"type": "object", "properties": {}, "required": [],
                                                             "additionalProperties": False}
    assert set(model.TOOL_INTENTS.values()) == set(copilot.INTENTS)


def test_the_loop_runs_tools_and_fills_the_answer():
    fake = FakeClient(reply(tool_use("zone_status"), stop="tool_use"),
                      reply(text("{{t1.name}} reads {{t1.risk_level}}.")))
    calls = []
    a = model.run(CTX, "how is this zone?", lambda name: calls.append(name) or result(ZONE), client=fake)
    assert calls == ["zone_status"] and a.text == "White Oak block G reads extreme." and a.placeholders == 2
    first, second = fake.requests
    assert first["model"] == model.MODEL and first["tools"] == model.TOOLS
    assert first["fallbacks"] == "default" and first["betas"] == [model.FALLBACK_BETA]
    assert "Selected zone: yes. Selected Case: none." in first["messages"][0]["content"]
    tool_reply = second["messages"][-1]["content"][0]
    assert tool_reply["tool_use_id"] == "tu1" and json.loads(tool_reply["content"])["result_id"] == "t1"


def test_parallel_tool_calls_get_their_results_in_one_message():
    fake = FakeClient(reply(tool_use("zone_status", "a"), tool_use("open_cases", "b"), stop="tool_use"),
                      reply(text("{{t1.risk_level}} / {{t2.risk_level}}")))
    model.run(CTX, "q", lambda name: result(ZONE), client=fake)
    replies = fake.requests[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in replies] == ["a", "b"]
    assert [json.loads(r["content"])["result_id"] for r in replies] == ["t1", "t2"]


def test_a_missing_selection_goes_back_to_the_model_as_a_tool_error():
    def call(name):
        raise copilot.CopilotInputError("the status of the selected zone needs a zone: select one on the map")
    fake = FakeClient(reply(tool_use("zone_status"), stop="tool_use"), reply(text("Select a zone on the map.")))
    with pytest.raises(model.Fallback, match="without reading any tool"):
        model.run(CTX, "q", call, client=fake)
    err = fake.requests[1]["messages"][-1]["content"][0]
    assert err["is_error"] is True and "select one on the map" in err["content"]


def test_out_of_scope_is_the_fixed_reply():
    a = model.run(CTX, "weather?", lambda name: result(ZONE), client=FakeClient(reply(text("OUT_OF_SCOPE"))))
    assert a.out_of_scope


# ---------------------------------------------------------------- fallbacks
def _fallback(fake, call=lambda name: result(ZONE)):
    with pytest.raises(model.Fallback) as exc:
        model.run(CTX, "q", call, client=fake)
    return exc.value


def test_a_rejected_answer_falls_back_to_the_template_of_the_tool_it_read():
    fb = _fallback(FakeClient(reply(tool_use("zone_status"), stop="tool_use"), reply(text("It is extreme."))))
    assert "rejected" in fb.reason and fb.intent == "zone_status"


def test_refusals_errors_cutoffs_and_endless_loops_fall_back():
    assert "declined" in _fallback(FakeClient(reply(stop="refusal"))).reason
    assert "cut off" in _fallback(FakeClient(reply(text("..."), stop="max_tokens"))).reason
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    assert "unreachable" in _fallback(FakeClient(anthropic.APIConnectionError(request=req))).reason
    loop = [reply(tool_use("open_cases"), stop="tool_use")] * model.MAX_ROUNDS
    assert "did not finish" in _fallback(FakeClient(*loop)).reason
    assert "without reading" in _fallback(FakeClient(reply(text("All is well.")))).reason


def test_real_household_data_is_never_sent_to_the_model():
    fake = FakeClient(reply(tool_use("briefing_facts"), stop="tool_use"), reply(text("unreachable")))
    fb = _fallback(fake, call=lambda name: result(ZONE, real={"h1"}))
    assert "real household" in fb.reason and fb.intent == "briefing"
    assert len(fake.requests) == 1 and fake.tool_payloads() == []


# ---------------------------------------------------------------- limits
def test_the_rate_limiter_is_a_sliding_window_per_key():
    lim = model.RateLimiter(limit=2, window=60)
    assert lim.admit("a", now=0) is None and lim.admit("a", now=10) is None
    assert lim.admit("a", now=20) == 40  # the first hit leaves the window at t=60
    assert lim.admit("b", now=20) is None  # another client is unaffected
    assert lim.admit("a", now=60) is None  # the first hit has left the window
    assert lim.admit("a", now=65) == 5
    lim.admit("c", now=200)
    assert set(lim._hits) == {"c"}  # keys idle for a whole window are dropped


def test_the_token_cap_stops_the_loop_and_shrinks_each_turn():
    fake = FakeClient(reply(tool_use("zone_status"), stop="tool_use", tokens=50000),
                      reply(tool_use("open_cases"), stop="tool_use", tokens=9000), reply(text("unreachable")))
    fb = _fallback(fake)
    assert "token cap" in fb.reason and fb.intent == "zone_status"
    assert [r["max_tokens"] for r in fake.requests] == [model.MAX_TOKENS, model.TOKEN_CAP - 50000]


def test_the_tool_call_cap_runs_no_tool_past_it():
    calls = []
    many = [tool_use("open_cases", f"u{i}") for i in range(model.MAX_TOOL_CALLS + 1)]
    fb = _fallback(FakeClient(reply(*many, stop="tool_use")), call=lambda name: calls.append(name))
    assert "tool-call cap" in fb.reason and fb.intent == "open_cases" and calls == []


# ---------------------------------------------------------------- the endpoint
@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture
def fake_key(monkeypatch):
    """A key is "set" but no client is ever built from it: each test installs a FakeClient."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")

    def refuse():
        raise AssertionError("a real client was built")
    monkeypatch.setattr(model, "make_client", refuse)


def use(monkeypatch, fake):
    monkeypatch.setattr(model, "make_client", lambda: fake)
    return fake


def _zone_with_case(client, run_id):
    zones = client.get("/map/zones", params={"run_id": run_id, "at": PEAK}).json()["features"]
    return next(f["properties"] for f in zones if f["properties"]["case_count"])


def test_without_a_key_no_client_is_built(client, runs, no_key, monkeypatch):
    monkeypatch.setattr(model, "make_client", lambda: (_ for _ in ()).throw(AssertionError("client built")))
    b = client.post("/copilot/ask", json={"run_id": runs["harvey"]["id"], "question": "open cases?"}).json()
    assert b["mode"] == "template" and "ANTHROPIC_API_KEY is not set" in b["mode_reason"]


def test_with_a_key_free_text_goes_to_the_model_and_values_match_the_map(client, runs, fake_key, monkeypatch):
    assert client.get("/copilot/status").json()["mode"] == "model"
    harvey = runs["harvey"]["id"]
    z = _zone_with_case(client, harvey)
    fake = use(monkeypatch, FakeClient(reply(tool_use("zone_status"), stop="tool_use"),
                                       reply(text("{{t1.name}}: risk level {{t1.risk_level}}, strongest Case "
                                                  "{{t1.confidence_word}}, data confidence {{t1.data_confidence}}."))))
    b = client.post("/copilot/ask", json={"run_id": harvey, "question": "how is this zone?", "zone_id": z["zone_id"],
                                          "at": PEAK}).json()
    assert b["mode"] == "model" and b["intent"] == "zone_status" and b["tools"] == ["zone_status"]
    assert b["answer"] == (f"As of 2017-08-27 18:30 UTC (REPLAY run):\n{z['name']}: risk level {z['risk_level']}, "
                           f"strongest Case {z['confidence_word']}, data confidence not assessed.")
    assert b["unknowns"] == ["t1.data_confidence"] and b["placeholders"] == 4
    sent = fake.tool_payloads()[0]["data"]
    assert "task_anchor" not in sent and sent["zone_id"] == z["zone_id"]


def test_with_a_key_a_rejected_answer_returns_the_template(client, runs, fake_key, monkeypatch):
    harvey = runs["harvey"]["id"]
    z = _zone_with_case(client, harvey)
    use(monkeypatch, FakeClient(reply(tool_use("zone_status"), stop="tool_use"), reply(text("This zone is extreme."))))
    body = {"run_id": harvey, "question": "how is this zone?", "zone_id": z["zone_id"], "at": PEAK}
    b = client.post("/copilot/ask", json=body).json()
    assert b["mode"] == "template" and "rejected: status word" in b["mode_reason"]
    template = client.post("/copilot/ask", json={**body, "question": "", "intent": "zone_status"}).json()
    assert b["answer"] == template["answer"]


def test_with_a_key_intent_buttons_still_use_templates(client, runs, fake_key):
    b = client.post("/copilot/ask", json={"run_id": runs["harvey"]["id"], "intent": "open_cases"}).json()
    assert b["mode"] == "template" and "intent was chosen" in b["mode_reason"]


def test_with_a_key_bad_inputs_fail_before_the_model(client, runs, fake_key):
    harvey = runs["harvey"]["id"]
    bad_run = "00000000-0000-0000-0000-000000000000"
    assert client.post("/copilot/ask", json={"run_id": bad_run, "question": "open cases?"}).status_code == 404
    early = {"run_id": harvey, "question": "open cases?", "at": "2016-01-01T00:00:00Z"}
    assert client.post("/copilot/ask", json=early).status_code == 422


def test_with_a_key_a_real_household_keeps_the_briefing_local(runs, fake_key, monkeypatch):
    connection = engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    app.dependency_overrides[get_db] = lambda: session
    try:
        client = TestClient(app)
        listening = runs["listening"]["id"]
        block_a = next(f["properties"] for f in client.get("/map/zones", params={"run_id": listening}).json()["features"]
                       if f["properties"]["name"].endswith("block A"))
        session.add(Household(zone_id=block_a["zone_id"], latitude=0.0105, longitude=0.0105,
                              age_bracket=AgeBracket.age_18_64, primary_language="en"))  # is_synthetic not set
        session.commit()
        fake = use(monkeypatch, FakeClient(reply(tool_use("briefing_facts"), stop="tool_use")))
        b = client.post("/copilot/ask", json={"run_id": listening, "question": "draft a briefing",
                                              "zone_id": block_a["zone_id"]}).json()
        assert b["mode"] == "template" and "real household" in b["mode_reason"]
        assert b["answer"].startswith("DRAFT RESPONDER BRIEFING") and b["household_data"]["real"] == 1
        assert fake.tool_payloads() == []  # nothing from the tool reached the model
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()
        outer.rollback()
        connection.close()


def test_with_a_key_the_per_ip_limit_falls_back_and_buttons_are_not_counted(client, runs, fake_key, monkeypatch):
    monkeypatch.setattr(model, "LIMITER", model.RateLimiter(limit=1, window=600))
    harvey = runs["harvey"]["id"]
    fake = use(monkeypatch, FakeClient(reply(tool_use("open_cases"), stop="tool_use"),
                                       reply(text("Here are the open Cases: {{t1.total}}."))))
    assert client.post("/copilot/ask", json={"run_id": harvey, "intent": "open_cases"}).json()["mode"] == "template"
    first = client.post("/copilot/ask", json={"run_id": harvey, "question": "summarize the open cases"}).json()
    assert first["mode"] == "model"
    second = client.post("/copilot/ask", json={"run_id": harvey, "question": "summarize the open cases"}).json()
    assert second["mode"] == "template" and "rate limit" in second["mode_reason"]
    assert second["intent"] == "open_cases" and 0 < second["retry_model_after_seconds"] <= 600
    assert len(fake.requests) == 2  # the limited question never reached the model
