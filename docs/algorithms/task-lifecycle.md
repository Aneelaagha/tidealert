# Task lifecycle

Status: **step 2 of 3.** The engine creates tasks and keeps them updated from
Case state, and people act on them through the API. Code:
- `backend/app/services/task_rules.py` (engine rules, run by the case
  matcher at the end of every sweep);
- `backend/app/services/task_actions.py` (people's actions);
- `backend/app/routes/tasks.py` (endpoints).

The map page does not show tasks yet (step 3).

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

- **The map page doesn't show tasks** (step 3). The map API already carries
  them.
- **Assignment is manual only:** no proximity, skills or routing.
  `route_geometry` stays empty.
- **Responder safety monitoring and supply routing:** Week 7.
