# Task lifecycle

Status: **step 1 of 3.** This step creates tasks and keeps them updated from
Case state. Assignment, endpoints and the map come in later PRs. Code:
`backend/app/services/task_rules.py`, run by the case matcher at the end of
every sweep.

## Rules (from Case state, on the run's clock)

After each sweep recomputes every Case's confidence word as of `now`:

| Rule | When | Effect |
|---|---|---|
| R1 | Fresh support (`single_source` or `corroborated`), no active task | Create a **pending** task. A zone Case gets `reach_block`; a household Case gets `welfare_check`. |
| R2 | The Case becomes `corroborated` | Set `cases.escalated_at` (once) and recompute priority. |
| R3 | The Case goes `stale_verify` | Flag `verify_before_dispatch`, with the reason: either the latest evidence contradicts the Case, or no support is fresh. |
| R3b | The Case has fresh support again | Clear the flag. |

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
cancelled. Only `pending` occurs so far; nothing assigns a task yet.

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

**Synthetic listening scenario:** 8 welfare checks and 1 `reach_block`.
- **Priority high:** the three help requests, the TROUBLE household, and the
  corroborated block Case. The TROUBLE household and the block Case were
  also escalated.
- **Priority low:** A2, flagged for verification after it answered by voice.

## Not yet

- **Assignment:** synthetic responders for scenario runs, and blocking
  assignment for replay runs, come in step 2. `responders.run_id` exists
  already.
- **Tasks ending:** none has been completed, cancelled or marked unable to
  reach. What R1 should do after a Case's task ends while the Case is still
  fresh is decided in step 2.
- **The map:** tasks are not on it yet (step 3).
