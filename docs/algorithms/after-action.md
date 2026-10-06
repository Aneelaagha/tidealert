# After-action report

What a run flagged, when, what was done about it, and what the system warned about, as of a time. Built only from
stored rows: nothing is estimated, and no text is written by a model.

- `backend/app/services/after_action.py`, `GET /reports/after-action?run_id=&at=` (`backend/app/routes/reports.py`).
  The response has the structured report and the same content as Markdown (`markdown`).
- Page: the **Report** button in the header opens the report for the run and time on screen, with **Download .md**.

## Labelled with the run's mode, first

| Mode | Label |
|---|---|
| replay | REPLAY of recorded data: a replay has no responders; its tasks show what the engines would have created |
| mixed | MIXED scenario: real recorded flood and isolation results, with SYNTHETIC responders and assignments, and needs and offers typed in by people; none of those are real |
| scenario | SYNTHETIC scenario: not a real event |
| live | LIVE run |

## Contents (each read from the endpoint the page already shows it from; `tests/test_after_action.py` checks them)

- **What was flagged:** Cases and zones (by confidence word and status), zones cut off / may be cut off / not assessed
  with the people recorded in them (supply access), tasks by status.
- **Timeline:** the first Case, the last Case flagged by that time, the first zone found cut off, the first
  reconnection, the recorded peak (only if it is on or before the as-of time), and every task action by a person or
  script, oldest first. The report does not know the future: an earlier as-of time omits later moments.
- **What was done:** a count of actions by people or scripts; on mixed and scenario runs it says they are scripted and
  synthetic. A replay records none and says so.
- **Warnings:** the zone-access warnings on active tasks (count by kind, first ten).
- **Needs and offers** (operator-entered, labelled so), **sources** at that time, the run's own **caveats**, and the
  report's **limits**.
- The Markdown also lists every Case flagged.

## What it does not say

- Whether the Cases were right: confidence words are unvalidated heuristics.
- What happened to people. It records what the system flagged and what was entered.
- Anything about a zone the isolation engine did not assess; those are counted apart.
