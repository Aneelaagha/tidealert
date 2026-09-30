# Case confidence: direction, derivation, and time decay

> **These are unvalidated heuristics, not calibrated probabilities.** Every
> factor below is computed from data the engines already have, but the
> weights, curves and half-lives are design choices. None has been
> calibrated against case outcomes: no case has a recorded outcome yet
> (`cases.validated`), and NFIP claims cannot confirm isolation. Values
> marked **GUESS** are choices with no measurement behind them at all.

Code: `backend/app/services/confidence.py` (decay and aggregation), plus
`isolation_cases.py`, `silence_baseline.py` and `listening.py` (derivations).

## Each contribution

A `CaseEngineContribution` stores four things:

- **`engine_confidence`:** how strongly this contribution supports the
  Case's claim (or, if it contradicts the Case, how strongly it argues
  against it), at the moment it was observed, before any decay.
- **`direction`:**
  - `supports`: evidence for the claim;
  - `contradicts`: evidence against it;
  - `neutral`: informative but neither, counted as 0;
  - `procedural`: a process step, not evidence, always stored with 0.
- **`observed_at`:** when the engine last observed the evidence. Evidence an
  engine keeps confirming (a block still cut off, a household still silent)
  is refreshed every sweep, so its value and time follow the latest
  confirmation.
- **`independent_sources`:** 1, or *k* for a depth report corroborated by *k*
  households.

| Evidence | Direction |
|---|---|
| Block cut off (opened, mechanism change, isolated again) | supports |
| Block reconnected | contradicts |
| Household late by its own baseline | supports |
| Household answered the check-in (SMS or voice) | contradicts |
| "I need help" reply, the household's own depth report, corroborated depth reports | supports |
| Neighbor `TROUBLE` | supports |
| Neighbor `SEEN_OK` | contradicts |
| Neighbor `CANT_SEE` | neutral (0) |
| Voice call placed, neighbor prompted, cascade exhausted | procedural (0) |

## Derivations

### Isolation

```
coverage x source_agreement x stage_provenance x library_range
```

- **`coverage`:** the share of the roads that cut the block off (exit roads,
  or boundary roads if the block is submerged) that are flooded by sample
  points the river driver covers.
  - **Finding:** for a confirmed isolation this is **1.0 by construction**,
    because a cut road is only counted as flooded when at least 2 covered
    sample points are under water. So it adds nothing today: it is a no-op
    until "possibly isolated" zones (the pessimistic side of bounded
    reachability, where unknown roads may be cut) start opening Cases too,
    and at that point it will actually discriminate.
  - It would only matter if Cases were ever opened from the pessimistic
    bound, where unknown roads are treated as cut. (A first implementation
    that counted any uncovered sample point as "unknown" wrongly zeroed most
    White Oak Cases; fixed before commit.)
- **`source_agreement`:** 1.0 for an NWS flood-map library. For HAND it is
  the median HAND-vs-NWS agreement (IoU over flooding timesteps) measured at
  gauges that have both, borrowed. Today that's 0.67, the mean of White Oak's
  0.64 and Greens' 0.70.
- **`stage_provenance`:** 1.0 when the gauge measured stage at that
  timestep, **0.7 (GUESS)** when stage was reconstructed from estimated
  discharge.
- **`library_range`:** 1.0 within the NWS library's mapped stages, **0.7
  (GUESS)** above its highest. Harvey never exceeded either library.
- **A reconnection** is scored with coverage 1.0 and direction
  `contradicts`.

In the Harvey replay this works out to source × stage provenance: White Oak
and Greens 1.00 on timesteps with measured stage and 0.70 on reconstructed
ones, Hunting 0.67 at every timestep (HAND, borrowed agreement).

### Silence

```
history x strength x reliability
```

- **`history`:** 0 below 5 answered check-ins (no verdict is ever "late"
  then), otherwise min(1, answered in window / 30).
- **`strength`:** 1 / (1 + exp(−(z − 3))), which is 0.5 at the flag
  threshold and about 0.95 at z = 6. The curve is a **GUESS**.
- **`reliability`:** 1 minus the household's historical never-answered rate.
- **A reply** (`contradicts`) is scored with the listening source base for
  its channel, below.

### Listening

```
source x corroboration count
```

- **The household's own reply:** SMS **0.8**, voice **0.85**. Both values are
  **GUESSES**. In particular, ranking voice above SMS (on the idea that a
  keypress is less likely to be a mistyped text) is an unvalidated design
  choice, not a finding.
- **Corroborated depth**, for *k* households:

  ```
  (1 − (1 − 0.8)^k) × (1 − 0.25 × spread)
  ```

  Spread is the number of steps between the shallowest and deepest report on
  ankle / knee / waist (0, 1 or 2). The disagreement reduction of **0.25 per
  step is a GUESS**, an unvalidated design choice, not a finding.
- **Neighbor reply:** **0.5 (GUESS)**. `TROUBLE` supports, `SEEN_OK`
  contradicts, `CANT_SEE` is neutral.
- **Cascade steps:** procedural, 0.

## Time decay (applied when read)

```
effective = engine_confidence × 0.5 ^ (age / half_life[engine])
```

Neutral and procedural contributions always count 0. Half-lives (**GUESSES**,
set by how fast each engine's evidence goes stale):

- silence: 30 min (it's about the household right now);
- listening: 2 h;
- isolation: 3 h (river stage changes over hours).

Evidence that is still being confirmed does not decay, because it is
refreshed every sweep.

## Case aggregation and the confidence word

Every sweep recomputes each Case's `confidence_word` as of that sweep:

- **Support:** the noisy-or of effective supporting contributions.
- **Contradiction:** the noisy-or of effective contradicting contributions.
- **`stale_verify`:** no supporting contribution is still fresh (effective ≥
  **0.25, GUESS**), or the most recent evidence contradicts the Case. It
  needs a human check.
- **`corroborated`:** fresh support from 2 or more independent sources, meaning
  two engines, or one contribution backed by 2 or more households.
- **`single_source`:** otherwise.

The engines never change a Case's status; closing a Case stays a human
decision.

**Harvey replay, confidence word over time** (open Cases per word):

| Time (UTC) | White Oak | Greens | Hunting |
|---|---|---|---|
| 8/27 06:00 | 3 single_source | 73 single_source | 8 single_source |
| 8/27 18:30 (White Oak peak) | 49 single_source | 73 single_source | 11 single_source |
| 8/29 00:00 | 4 single_source, 45 stale_verify | 73 single_source, 19 stale_verify | 8 single_source, 3 stale_verify |
| 9/3 05:00 (end) | 49 stale_verify | 92 stale_verify | 11 stale_verify |

By the end of the replay every block has reconnected, so every Harvey Case's
latest evidence contradicts it and all read `stale_verify`. The words change;
the Cases themselves do not.

Compared tick by tick with the previous engine (constant confidences, word
fixed at `single_source` for Harvey), all 152 Harvey Cases read differently
at some point. That's 72,187 of 99,699 Case-ticks, all `single_source` →
`stale_verify`, and every one falls after a reconnection; none is decay while
a block is still isolated. Harvey zones have no registered households, so
only isolation contributes there.
