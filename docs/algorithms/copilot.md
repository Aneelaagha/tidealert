# Copilot

Status: **step 3 of 3.** Grounded tools, template answers, model-backed
answers for free-text questions, and the copilot panel on the map page.

Code:
- `backend/app/services/copilot_tools.py` (tools);
- `backend/app/services/copilot.py` (routing, templates, mode choice);
- `backend/app/services/copilot_model.py` (model mode: tool loop, rejection
  check, placeholders);
- `backend/app/routes/copilot.py` (endpoints).

## Scope

No spec wording exists beyond "AI copilot". The scope below was agreed with
the project owner:

| Intent | Answers | Needs |
|---|---|---|
| `zone_status` | The selected zone: risk level (and why it reads unknown), data confidence, coverage gaps, Case and task summaries | a zone |
| `zone_cases` | Every Case in the selected zone, with its latest evidence and task | a zone |
| `open_cases` | The run's open Cases, strongest confidence first | — |
| `explain_confidence` | Why a Case has its confidence word: the rule, and each contribution's confidence before and after decay against the freshness threshold | a Case |
| `briefing` | A **draft** responder briefing for a zone, labelled as a draft to verify | a zone |

Anything else gets a fixed out-of-scope reply, never an answer from general
knowledge.

## Endpoints

- `POST /copilot/ask` takes:
  - `run_id`;
  - optionally `question`, `intent`, `at`, `zone_id` and `case_id`.

  Without `intent`, the question goes to the model in model mode, or is
  routed by keywords in template mode. The answer is stated as of `at` on
  the run's clock (the map's slider time, default the end of the window) and
  says the run's mode. Every answer reports the `mode` that produced it and
  why (`mode_reason`).
- `GET /copilot/status` returns the current mode and its reason, the
  intents, and `needs`: what each intent needs selected (`zone_id` or
  `case_id`). This is the same table `/copilot/ask` checks, so the page can
  say why a button is off.

## Panel (map page)

`frontend/src/components/CopilotPanel.tsx` puts the copilot on the map
page. It calls only `/copilot/status` and `/copilot/ask`; there's no other
model, SDK or server behind it.
- **Header:** the mode and its reason from `/copilot/status`. Without a key
  that reads "TEMPLATE MODE: ANTHROPIC_API_KEY is not set: answers come from
  fixed templates".
- **Questions:** the five intent buttons, labelled from the intents. A
  button is disabled with its reason when its selection is missing, and the
  hint below groups them (for example "zone status, zone cases, briefing:
  needs a zone: select one on the map"). A free-text box sends the question
  with the run, the slider time, the selected zone, and the Case selected in
  the Cases panel.
- **Each answer shows:**
  - its MODEL or TEMPLATE badge, and OUT OF SCOPE when it is;
  - its intent and its `mode_reason`. A template answer while the copilot
    is in model mode is labelled "Fell back to templates".
  - `served_by` when present;
  - any unknowns;
  - the household count and how many are real;
  - when rate limited, the time until model questions are available again.
- **When the copilot can't answer yet** (a 422: a missing selection, or a
  time outside the run), the reply is an amber "Can't answer yet" notice
  with the server's text, not an error. Other failures show their HTTP
  status in red.
- **The log is display only:** the backend answers each question on its
  own, and the panel says so. The log clears when the run changes.

## Grounding

- **Every value comes from a tool.** The tools reuse the map's own queries
  (`map_state`), so the copilot and the map can't disagree. Tests check that
  the stated risk level and confidence word equal the map's values for 25
  Harvey zones.
- **Gaps are stated, not filled.** A null `data_confidence` reads "not
  assessed". An unknown risk level gives the stored reason, or "not assessed
  by any engine". A zone with no Case says so. Missing inputs return 422,
  and objects not in the run return 404.
- **Template mode** builds every answer from tool results with fixed
  templates. It's used when `ANTHROPIC_API_KEY` is not set, when the request
  names an `intent` (a button has already chosen the tool, and the template
  is exact), and whenever model mode falls back.
- **Model mode** (`ANTHROPIC_API_KEY` set, free-text question) is described
  below.

## Model mode

- **Model:** `claude-opus-5-5` at effort `medium`, through the Messages API
  with tool use. Server-side refusal fallback is on (`fallbacks: "default"`):
  if the model declines, the API reruns the request on a fallback model, and
  the answer reports the model that served it (`served_by`).
- **Tools:** the five grounded tools (`zone_status`, `zone_cases`,
  `open_cases`, `explain_confidence`, `briefing_facts`). They take **no
  arguments**: the zone and Case are the map's selection, so the model can't
  read beyond it. A missing selection goes back to the model as a tool error,
  so it can ask the user to select one.
- **Placeholders:** each tool result gets an id (`t1`, `t2`, ...). The model
  sees the values, so it can decide what matters, but it writes facts only
  as `{{t1.risk_level}}`, `{{t1.cases[0].confidence_word}}` and so on. The
  server fills each one from the stored tool result with the same formatting
  as the templates (null reads "not assessed"). The server, not the model,
  writes the "As of ... (REPLAY run)" line, and for a briefing the draft
  label and run caveats.
- **Rejection check:** before filling, the model's own words (everything
  outside placeholders) are rejected if they contain:
  - a **status word**, in stored form or with spaces. The list is built from
    the enums: risk levels, confidence words, Case and task statuses, task
    priorities, household statuses and source freshness. The one exception
    is the phrase "open Case(s)", which names a question, not a status.
  - a **digit**. Counts, confidences, times and populations must all be
    placeholders.
  - a **copy of any tool string** of 8 or more characters (zone names,
    inference sentences, rules) that isn't an enum value.
  - a placeholder that names no tool result, no value, or a group of values,
    or stray braces.
- **Fallback to templates:** a rejected answer is never shown. The copilot
  answers with the template for the first tool the model read (or the
  keyword route), and `mode_reason` says why. The same fallback covers a
  refusal from the whole fallback chain, a cut-off answer, an API error, an
  answer that read no tool, and more than 6 model turns.
- **Out of scope:** the model replies with a fixed token, and the server
  returns the fixed out-of-scope reply.
- **Limits:** these apply only to model calls. Template answers are not
  counted or limited. Hitting any limit falls back to the template, and
  `mode_reason` says which limit.
  - **Per client IP:** 20 model questions per 10 minutes, as a sliding
    window. A limited answer also reports `retry_model_after_seconds`.
  - **Per question:** a cap of 60,000 tokens (input plus output, summed over
    the model's turns). Each turn's `max_tokens` is cut to what's left, and
    no turn starts with less than 2,048.
  - **Per question:** at most 8 tool calls and 6 model turns. A turn that
    would go past the tool-call cap runs none of its tools.
- **Setup:** `ANTHROPIC_API_KEY` in the repo-root `.env` (loaded by
  `app/database.py`) or in the environment, plus the `anthropic` package
  (`requirements.txt`). With either missing, the copilot stays in template
  mode.

## Household data and external models

- **What's never returned:** household fields the map doesn't show (phone,
  age bracket, disability, income, language, exact location).
- **Every result reports** which households its data came from (a household
  Case, or a zone Case built from silence or listening evidence) and how many
  are **real**.
- **`households.is_synthetic`** marks generated test households. It
  **defaults to false**, so an unmarked household counts as real. The
  generator scripts set it explicitly.
- **The guard:** a result that touches any real household has
  `may_send_to_external_model: false`. The model path never sends it: the
  question falls back to the template for that tool, and nothing from the
  result reaches the model. This is checked on every result, not assumed. A test adds an
  unmarked household to a zone and confirms the briefing becomes unsendable.

## Known limitations

- **Model mode is untested against the live API:** the tests drive the
  tool loop with a scripted stand-in for the API. Tool calling, the
  rejection check, placeholder filling and every fallback are tested, but
  how often the real model's answers pass the check is not yet measured.
- **The rejection check is lexical:** it catches written status words,
  digits and copied text. It doesn't catch a count spelled out in words
  ("two Cases"), or a wrong claim made without a value (for example, "this
  zone has no Cases" when it has some). Values that come through
  placeholders can't be wrong, since the server fills them.
- **Strict on purpose:** a digit anywhere in the model's own words (even
  "Case 1"), or a priority word like "high", rejects the answer.
  Rejections fall back to templates, so the cost is a plainer answer, not a
  wrong one.
- **Recorded text vs. confidence:** a contribution's text is written when the
  evidence is first observed, and evidence the engine keeps re-confirming has
  its confidence updated later. The explanation shows both and says they can
  differ. For example, a White Oak contribution's text says 1.00 (measured
  stage), but its last confirmed value is 0.70 (reconstructed stage).
- **Zone Cases count every household in the zone:** for a zone Case built
  from household evidence, the evidence doesn't link each contributing
  household, so all households in the zone are counted (the conservative
  choice).
- **The rate limit is in process memory:** it resets when the server
  restarts, and each worker process counts separately. The client IP is the
  direct peer, and proxy headers (`X-Forwarded-For`) are not trusted, so
  behind a reverse proxy every user shares the proxy's quota. All of this is
  fine for one local process. A deployment would need a shared store and a
  trusted-proxy setting.
- **The token cap is checked between turns:** the input of the turn that
  crosses it is already spent, so one question can overrun the cap by up to
  one turn's input.
