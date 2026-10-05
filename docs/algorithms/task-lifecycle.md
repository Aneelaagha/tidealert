# Task lifecycle

Status: **step 3 of 3.** The engine creates tasks and keeps them updated from
Case state, people act on them through the API, and the map page shows them
(read-only). Code:
- `backend/app/services/task_rules.py` (engine rules, run by the case
  matcher at the end of every sweep);
- `backend/app/services/task_actions.py` (people's actions);
- `backend/app/routes/tasks.py` (endpoints).

- the map page (`frontend/`, see [docs/api/map.md](../api/map.md)): task
  markers, legend, zone-panel task history, the task-event feed, and assign
  and mark-complete controls on scenario and live runs.

## Rules (from Case state, on the run's clock)

After each sweep recomputes every Case's confidence word as of `now`:

| Rule | When | Effect |
|---|---|---|
| R1 | Fresh support (`single_source` or `corroborated`), no active task | Create a **pending** task. A zone Case gets `reach_block`; a household Case gets `welfare_check`. **After a person closed the last task**, only *new* supporting evidence (first observed after the close) creates one. Evidence the engine merely keeps re-confirming doesn't count, or every close would be undone on the next sweep. |
| R2 | The Case becomes `corroborated` | Set `cases.escalated_at` (once) and recompute priority. |
| R3 | The Case goes `stale_verify` | Flag `verify_before_dispatch`, with the reason: either the latest evidence contradicts the Case, or no support is fresh. |
| R4 | An **independent source contradicts** the Case (today: the nominated neighbor's SEEN_OK) | Flag `verify_before_dispatch` **whatever evidence is more recent**. A conflict between sources needs a person before anyone is sent; the household's own silence, re-confirmed every sweep, must not hide it. |
| R3b | Fresh support again, and no R4 conflict stands | Clear the flag. Only a person clears an R4 flag. |

When a person clears a flag (`verify_cleared_at`), R3 and R4 only flag
again on evidence newer than the clearance.

- **Nothing is dispatched automatically.** Pending means waiting for a person
  to assign the task.
- **Evidence never completes or cancels a task.** Only a person does.
- **Every change** is recorded as a `task_events` snapshot (status,
  priority, verify flag, assignee, actor, note), so a task can be read back
  as of any time.

**Priority** is an ordinal and a **design choice**, not calibrated against
outcomes:

| Priority | When |
|---|---|
| low | verify-flagged |
| high | corroborated Case, a household asked for help, or its nominated neighbor reported trouble |
| medium | otherwise |

A medium task is raised to high for a household that is 65+ or has a
disability. Those fields exist but hold only synthetic values, and no
current household qualifies.

**Statuses:** pending → assigned → en_route → complete / unable_to_reach /
cancelled.

## What people do (API)

| Endpoint | Action |
|---|---|
| `POST /tasks/{id}/assign` | Assign a pending task to a responder. |
| `POST /tasks/{id}/status` | Move it to `en_route`, `complete`, `unable_to_reach` or `cancelled`. |
| `POST /tasks/{id}/clear-verify` | A person has checked the evidence. Priority goes back to its level before the flag, taken from the task's history. |
| `POST /cases/{id}/tasks` | Open a follow-up task on a Case with no active task, for example after `unable_to_reach`. |
| `GET /tasks`, `GET /tasks/{id}`, `GET /responders` | Read tasks as of `at` (from `task_events`) and the run's responders. |

Every action records a `task_events` snapshot with the actor. The rules:

- **Replay runs refuse every action (422).** Harvey's tasks show what the
  engines would have created; an assignment in 2017 would invent a dispatch
  history.
- **A task flagged `verify_before_dispatch` can't be assigned (409)** until a
  person clears the flag.
- **The responder must be available** (one active task at a time).
- **The responder must belong to the task's run:** a synthetic responder of
  that scenario, or a real responder for a live run.
- **Assigning sets the Case to `in_progress`.** Completing a task never
  resolves the Case; that stays a separate human decision.
- **Closing a task frees the responder** and leaves the Case without an
  active task.
- **Actions use the run's clock:** inside a scenario's window, defaulting to
  its end. They can't be earlier than the task's latest event.
- **There's no authentication:** `actor` is free text.

**Synthetic responders:** `scripts/seed_synthetic_responders.py <scenario
run>` creates four "Synthetic responder N" rows tied to that run. They have
no location and a neutral role, and no skills are modelled. The script
refuses replay and live runs.

## Results

**Harvey replay:** 152 tasks, one per Case.
- All are `reach_block` and all still `pending`.
- Each was created at the tick its Case opened, at priority medium.
- By the end of the window all 152 are flagged `verify_before_dispatch`
  (priority low), because every block reconnected and the reconnection
  contradicts the Case.
- On 3 Hunting tasks the flag was cleared 6 times when the block was cut off
  again, then set again.
- No Harvey Case is ever corroborated, so none is escalated.

**Synthetic listening scenario:** 7 welfare checks and 1 `reach_block`. (The
silence scenario has 1 more welfare check. PR #4 miscounted these as "8 + 1"
for the listening run.)
- **R4:** A3's task (its neighbor said SEEN_OK while the household stayed
  silent) is flagged by R4 at 14:45, priority low.
- **Priority high:** the three help requests, the TROUBLE household, and the
  corroborated block Case. The TROUBLE household and the block Case were
  also escalated.
- **Priority low:** A2, flagged for verification after it answered by voice,
  and A3 (R4).

## Not yet

- **No task controls on the map page:** assigning and status changes are
  API-only.
- **Assignment is manual only:** no proximity, skills or routing.
  `route_geometry` stays empty.
- **Supply routing:** Week 7 (route feasibility only).

## Responder safety: zone access (step 1)

`app/services/safety.py` adds a `safety` block to every task state from
`/tasks`, `/tasks/{id}`, `/cases` and the task actions. It's computed as of
the slider time from what the isolation engine already stored, in one
batch per request. Nothing new is measured.

| `zone_access` | When | Warning (active tasks) |
|---|---|---|
| `isolated` | the zone's latest isolation evidence at `at` supports isolation (mechanism: stranded or submerged) | **high**: "Zone cut off since T". If nobody is assigned it says so. If the current assignee was assigned before T: **"cut off after the responder was assigned"** (`isolated_after_assignment`). |
| `reconnected` | the latest isolation evidence is a reconnection | none; the reconnection text is shown, as the optimistic bound, not as "reachable" |
| `possibly_isolated` | the zone's time-bound "possibly isolated" coverage gap is active | **medium**: "Zone may be cut off since T" |
| `not_evaluated` | a permanent coverage gap, or the isolation engine never ran on the zone's region (every synthetic scenario zone) | none; the panel says "not a sign it's safe" |
| `reachable` | evaluated, no gap, never isolated: a dry route exists even if every unknown road is flooded | none |

**"Since" is the start of the isolation:** the first "cut off" row after
the zone's latest reconnection. One isolation can carry several rows as its
mechanism changes ("now submerged", "now stranded"); the mechanism shown is
the latest row's. Step 1 first took "since" from the latest row, which
moved "since" forward in the middle of an isolation: on Harvey that put it
24–25 zones late at a given time. A responder assigned during an isolation
would have been warned "cut off after assignment". Fixed in step 2a.

**What the warnings rest on:**
- "Reachable only over flooded roads" is the `isolated` state. No
  route-by-route flood state is stored, so there are no routes to show.
- When no responder is assigned to an isolated or possibly isolated zone,
  `assignment_note` says "no assignment to warn about…" rather than staying
  silent.

**By run:**
- **Harvey:** every reach-block task carries a real cut-off warning while
  its zone is isolated, and reads reconnected afterwards. No responders
  exist and replays refuse assignments, so `isolated_after_assignment`
  can't occur.
- **The synthetic scenarios:** read `not_evaluated` throughout.

The after-assignment logic is tested on its own (`tests/test_safety.py`).
It will be exercised against a real timeline by step 2: synthetic
responders over Harvey, labelled as a mixed scenario.

The page shows the warnings in the Cases panel, the zone panel and the
Responders panel. The map is unchanged.

## Responder safety: the mixed scenario (step 2)

`scripts/mixed_harvey_scenario.py` builds the run
`mixed:harvey-synthetic-responders:2017-08-25..2017-09-02`, with mode
**`mixed`**: Harvey's real flood and isolation results, with a synthetic
responder layer on top.

**The flood layer is real, not copied.** The case matcher reruns on the same
recorded USGS gauge data as the Harvey replay, under its own source labels
(`mixed:2017-08-25..2017-09-02:USGS-<site>`). It never reuses Harvey's
`backtest:…` labels, because `clear_cases` deletes Cases by source label
across runs. Its 152 Cases equal Harvey's, Case for Case: site, zone, opened
time, confidence word and contribution count (tested).

**The synthetic layer:**
- 6 responders ("Synthetic responder 1–6").
- Scripted assignments, made through the real `task_actions.assign` at their
  run-clock tick, right after that tick's sweep. An action can't be stamped
  earlier than a task's latest event, so assigning after the replay finished
  would be refused.
- The actor is `script:mixed-scenario (synthetic)`.
- A reconnection contradicts a Case, so its task is flagged "verify before
  dispatch", and the real assign refuses flagged tasks. For those, the
  script first records a scripted `clear_verify`, as an operator would.

**Who is assigned what.** The rules are fixed and nothing is random, so
rerunning rebuilds identical state (tested). All five rules read Harvey's
real isolation evidence:

| Responder | Rule | Assigned | Expected |
|---|---|---|---|
| 1–3 | every Case cut off, reconnected and cut off again with ≥ 30 min reconnected: 3 Hunting Bayou blocks, reconnected 2017-08-28 02:15, cut off again 03:45 | 08-28 02:30 | reconnected, no warning, until 03:45; **`isolated_after_assignment` from 03:45** |
| 4 | control: the first single-isolation Case, 15 min after its isolation began | 08-27 04:15 | `zone_isolated`, "assigned after that" |
| 5 | control: the next single-isolation Case, 15 min after it reconnected | 08-29 20:30 | reconnected, no warning |
| 6 | not assigned | | |

**What this does and doesn't show.** The after-assignment warning fires on a
real engine transition in this run. But it rests on 3 blocks, on Hunting
Bayou's lower-confidence driver (HAND plus a fallback threshold), and one
usable 1.5-hour window. It shows the warning works on real state changes,
not how often they happen.

**Labelling.** The mode is registered, never inferred, so it follows the run
everywhere:
- the badge is a striped teal **MIXED: REAL FLOOD + SYNTHETIC RESPONDERS**;
- the run picker says "Mixed scenario: Harvey's real flood + synthetic
  responders";
- the caveat, always in the banner, says "Mixed scenario: Harvey's real
  recorded flood and isolation results, with synthetic responders and
  assignments layered on top. The responders, assignments and anything they
  cause are not real." The replay caveat is shown too;
- the ethics panel has a meaning for the mode;
- the copilot's as-of line says "MIXED run".

**Migration and restore.** The `run_mode` enum gains `mixed` (migration
`b7e3f0a91c52`). Its downgrade refuses while any mixed run exists. Both the
round trip and the refusal are tested inside rolled-back transactions.
Rerunning the script resets the mixed run, including anything done to it
in the UI.
