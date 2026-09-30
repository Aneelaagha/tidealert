# Listening engine: probe cascade, survivor reports, nominated neighbors

Status: **logic built and exercised on synthetic households only.**

- There is no live registry.
- Nothing is actually sent: there are no SMS or voice credentials.
- None of the timings or thresholds is calibrated.

Code: `backend/app/services/listening.py`, run by the case matcher
(`backend/app/services/case_matcher.py`). Scenario:
`scripts/listening_demo.py`.

## Probe cascade

Every step is a `ProbeResponse` row linked to the check-in by
`parent_probe_id`, with a `purpose` of `checkin`, `depth_followup` or
`neighbor_prompt`.

```
check-in SMS --late for this household--> automated voice call --10 min-->
prompt to the nominated neighbor --30 min--> exhausted
```

- **When the SMS escalates:** when the household is late by its **own**
  silence baseline. With too little history, after a fixed 15 minutes.
- **A reply ends the cascade.** A reply by SMS or on the voice call ends it.
  "OK" closes it. "HELP" sends a depth question (ankle / knee / waist).
- **No nominated neighbor:** the cascade goes straight from an unanswered
  voice call to exhausted.
- **Late replies still count:** an exhausted cascade stays open, so a late
  answer from the household is recorded.
- **The neighbor's reply** is a second, independent signal about the
  household:
  - `TROUBLE` confirms the silence;
  - `SEEN_OK` explains it;
  - `CANT_SEE` means the neighbor couldn't see the home.

## Survivor as sensor

- **Every depth answer is visible** as a `Signal` (type `reported`, variable
  `depth_reported`) linked from the probe.
- **A single report never changes the zone.**
- **Corroboration:** when 2 or more different households in the same street
  block report within 2 hours, the block's state changes:
  - their probes are marked `is_corroborating`;
  - their Signals are linked (`corroborates_signal_id`);
  - the block's `risk_level` is raised to the level of the depth that at
    least two of them reached: ankle → elevated, knee or waist → extreme. It
    is never lowered automatically. A zone nobody has assessed is `unknown`
    (the default), never `safe`.

## Cases (via the case matcher)

Contributions from this engine use `engine = listening`.

| Signal | Case effect |
|---|---|
| "I need help" reply | Joins the block's open isolation Case, or the household's Case, or opens a household Case. The block's `risk_level` is not touched. |
| Single depth report | Added to the household's own Case only. |
| 2+ corroborating depth reports | Joins the block's isolation Case, or opens or updates a block-level Case. |
| Neighbor `TROUBLE` | Added to the household's Case (supports), or opens a household Case. |
| Neighbor `SEEN_OK` / `CANT_SEE` | Recorded on an existing Case as an explanation. It never closes the Case, which stays a human decision. |
| Voice call, neighbor prompt, exhausted | Recorded on the household's existing Case. |

**Design decision to review:** an explicit "I need help" reply opens a
household Case on its own, without corroboration. It is a direct request
from one household, not a claim about the block, so the zone state is not
touched, but it is not suppressed either.

No row sets the confidence word directly. Each sweep recomputes it from the
Case's decayed evidence ([confidence.md](confidence.md)): `corroborated`
needs fresh support from two engines or two households, so a TROUBLE report
that has aged out no longer corroborates.

## Synthetic scenario (`scripts/listening_demo.py`)

The scenario has 9 households in two blocks, each with 20 days of check-in
history, swept every 15 minutes from 14:00:

| Household | Script | Result |
|---|---|---|
| A1, B2 | answer the SMS | no escalation, no Case |
| A2 | misses the SMS, answers the voice call | voice at 14:15, answered; silence Case notes the voice reply |
| A3 | silent; neighbor: SEEN_OK | voice 14:15, neighbor 14:30; Case gets the explanation, stays open |
| A4 | silent; neighbor: TROUBLE | voice 14:15, neighbor 14:30; Case becomes **corroborated** (back to single_source once the TROUBLE report decays, about 2 h later) |
| A5 | silent, no nominated neighbor | voice 14:15, **exhausted** 14:30 |
| A6, A7 | HELP → knee / waist | help Cases; the two reports, 27 min apart, **corroborate**: block A `unknown` → `extreme`, block Case opened |
| B1 | HELP → ankle | single report: visible, block B stays `unknown` |

The Harvey isolation replay and the silence-only replay are unchanged by
this work (same Cases).

## What is a placeholder or unvalidated

- **No real messaging.** `TwilioTransport` raises "not implemented".
  `SimulatedTransport` plays scripted replies.
- **No street addresses.** Households have no address field, so the neighbor
  prompt says "the home at (lat, lon)", not "412 Oak St".
- **Cascades live in memory.** Open cascades are tracked only by the engine
  that started them, so a restart loses them. A live system needs a
  persisted cascade state.
- **Escalation is only as fast as the sweep.** Escalations happen at sweep
  ticks, so a step can wait up to 15 minutes past its deadline. In the
  scenario A2 was late at 5 minutes but called at 14:15.
- **Open gap: an exhausted cascade goes nowhere.** When a household
  answers neither the SMS nor the voice call and has no nominated neighbor
  (A5 in the scenario), the cascade ends as exhausted with no further
  escalation: no responder task, no second contact, no welfare check. The
  silence Case records it, but nothing acts on it. Not fixed yet.
- **Starting check-ins is out of scope.** What starts a cascade (for example
  a gauge alarm) is not built. The scenario starts check-ins by hand.
- **Uncalibrated values:** the timeouts (15 / 10 / 30 min), the
  corroboration rule (2 households, 2 hours), the depth-to-risk mapping and
  confidence values (household SMS 0.8 / voice 0.85, neighbor 0.5, and the
  corroboration disagreement reduction). These are guesses; see
  [confidence.md](confidence.md).
- **Nothing tested on real people.** All behavior above comes from scripted
  synthetic replies. No real response patterns, false reports or neighbor
  reliability have been checked.
