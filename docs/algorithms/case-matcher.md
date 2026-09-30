# Case matcher

A periodic sweep that opens and updates Cases from the isolation and silence
engines. It replaces the one-off Case writing the isolation pipeline used to do.

Code: `backend/app/services/case_matcher.py`, run by
`scripts/run_case_matcher.py`.

```bash
# Replay Hurricane Harvey for three gauges (run the isolation pipeline for each first)
.venv/bin/python scripts/run_case_matcher.py 08074500 08076000 08075770

# Silence-only replay over the synthetic test households
.venv/bin/python scripts/run_case_matcher.py --silence-region synthetic:silence-baseline \
    --start 2026-09-02T14:00Z --end 2026-09-02T19:00Z
```

## How it runs

- **Scheduler:** an asyncio loop runs one sweep per gauge on every clock tick,
  **every 15 minutes** by default (`--cadence-minutes`).
- **Replay clock:** steps through a past event window without waiting. This
  is the only mode for now.
- **Live clock:** would sleep 15 minutes between sweeps. It needs a live
  household registry and probe cascade that do not exist yet, so `--live`
  exits with that explanation.

## What one sweep does

A sweep uses only information as of its time `now`.

**Isolation.** It runs the isolation engine at `now`, using the river level
at that timestep, with unknown roads passable, so isolation is confirmed.

- A newly isolated zone opens a Case. The inference sentence and the rule
  fragment describe the mechanism.
- A zone that stays isolated updates `last_contribution_at`.
- Each of the following appends a contribution to the Case:
  - a change of mechanism (stranded to submerged),
  - a reconnection (a route to the main road network is open again),
  - a renewed isolation.
- The engine never resolves or closes a Case. That is a human decision.

**Silence.** It looks at each household's most recent probe as of `now`.
Older unanswered probes are moot once a later one has been answered. If that
probe is still unanswered at `now`, it is judged against the household's own
baseline from earlier probes. A late household is handled like this:

- **Matching:** if its zone has an open isolation Case, the silence flag
  joins that Case as a second engine, and `confidence_word` becomes
  `corroborated`.
- **Otherwise:** it opens (or adds to) a household Case, with `household_id`
  set.
- **Later:** the household's eventual response is recorded as a
  contribution.

`engine_confidence` values are ordinal tiers, not calibrated probabilities:
isolation 0.8 (NWS map) or 0.4 (HAND), silence 0.5.

## Replay labels

Each replay writes Cases under a `source` label such as
`backtest:2017-08-25..2017-09-02:USGS-08074500`. A rerun replaces that label's
Cases and never touches live Cases or other replays.

**Replay caveat:** the river level at each step comes from the published USGS
record. That record includes values estimated after the event, and the rating
curve is fitted to the whole event. A live system would only have had
provisional data at the time.

## Checks

- **Same results as the bulk writer.** The Harvey replay opens exactly the
  Cases the old bulk writer did (same zones, same opening times): 49 White
  Oak, 92 Greens and 11 Hunting. It also records the later reconnections and
  mechanism changes (51, 168 and 33 contributions).
- **Silence on synthetic households** (2026-09-02 14:00–19:00 UTC), one Case
  in total:
  - The fast responder is flagged 15 minutes after an unanswered probe.
  - Its 30-minute answer is recorded.
  - It is flagged again for its next unanswered probe.
  - The slow responder, answering in the same 30 minutes, is never flagged.
- **Matching,** tested in a rolled-back transaction: a household added to
  White Oak's first isolated block, with a probe left unanswered, joined that
  block's isolation Case at the same sweep, and the Case became
  `corroborated`.
- **Bug fixed during testing:** the first silence sweep flagged households
  for probes left unanswered weeks earlier (20 false Cases). Only each
  household's latest probe counts now.
