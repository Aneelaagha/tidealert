# Copilot

Status: **step 1 of 3.** Grounded tools and a template-answer endpoint. The
model-backed answers (step 2) and the side-panel UI (step 3) come next.

Code:
- `backend/app/services/copilot_tools.py` (tools);
- `backend/app/services/copilot.py` (routing and templates);
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

  Without `intent`, the question is routed by keywords in template mode. The
  answer is stated as of `at` on the run's clock (the map's slider time,
  default the end of the window) and says the run's mode.
- `GET /copilot/status` returns the current mode and the intents.

## Grounding

- **Every value comes from a tool.** The tools reuse the map's own queries
  (`map_state`), so the copilot and the map can't disagree. Tests check that
  the stated risk level and confidence word equal the map's values for 25
  Harvey zones.
- **Gaps are stated, not filled.** A null `data_confidence` reads "not
  assessed". An unknown risk level gives the stored reason, or "not assessed
  by any engine". A zone with no Case says so. Missing inputs return 422,
  and objects not in the run return 404.
- **Template mode** (automatic when `ANTHROPIC_API_KEY` is not set) builds
  every answer from tool results with fixed templates.
- **Model mode** (step 2) will have the model write placeholders that the
  server fills from tool results, and reject any status word the model
  writes itself.

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
  `may_send_to_external_model: false`, and the model path (step 2) refuses to
  send it. This is checked on every result, not assumed. A test adds an
  unmarked household to a zone and confirms the briefing becomes unsendable.

## Known limitations

- **No model yet:** template mode only. Free-text questions are routed by
  keywords.
- **Recorded text vs. confidence:** a contribution's text is written when the
  evidence is first observed, and evidence the engine keeps re-confirming has
  its confidence updated later. The explanation shows both and says they can
  differ. For example, a White Oak contribution's text says 1.00 (measured
  stage), but its last confirmed value is 0.70 (reconstructed stage).
- **Zone Cases count every household in the zone:** for a zone Case built
  from household evidence, the evidence doesn't link each contributing
  household, so all households in the zone are counted (the conservative
  choice).
- **No rate limiting yet** (step 2, together with the model call).
