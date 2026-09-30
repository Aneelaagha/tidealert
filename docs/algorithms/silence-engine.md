# Silence engine: per-household response baseline

Status: **statistics only, tested on synthetic data.** There is no live
household registry and no SMS/voice integration yet.

The silence engine asks whether a household has gone quiet *for them*.
Response habits differ enormously: one household answers a check-in text in
a minute, another always takes 40. A single "late after N minutes" rule
either misses the fast responders or keeps flagging the slow ones, so each
household is judged against its own history.

Code: `backend/app/services/silence_baseline.py`.

## Method

Latency is `responded_at - sent_at` of a `ProbeResponse`. Per household, over
its last 30 answered probes:

| Stored on `Household` | Meaning |
|---|---|
| `median_response_seconds` | median latency |
| `response_variance_seconds` | variance of latency (seconds², as the column name says) |
| `probe_count` | every probe sent, answered or not |

Latencies are right-skewed, so lateness is judged on the log scale with
robust statistics:

```
z = (log(elapsed) - median(log latency)) / scale
scale = max(1.4826 * MAD(log latency), log(1.25))
late  when  z > 3
```

`elapsed` is the response time for an answered probe, or the silence so far
for one still unanswered. The scale floor keeps a very regular responder from
being flagged for ordinary jitter. With fewer than 5 answered probes the
verdict is `insufficient_history`, never `late`.

The window (30), minimum history (5), threshold (z > 3) and scale floor (±25%)
are statistical choices. None is calibrated against real households.

## In the case matcher

Every 15 minutes the case matcher ([case-matcher.md](case-matcher.md))
judges each household's most recent probe, if it is still unanswered.
Older unanswered probes are moot once a later probe has been answered. A
late household joins its zone's open isolation Case (making it
`corroborated`) or opens a household Case.

## Synthetic test

`scripts/generate_synthetic_probes.py` creates 24 test households in a zone
labelled `synthetic:silence-baseline`. Each has its own log-normal response
habit (medians from 45 s to 1 h, plus a share of unanswered probes), for 960
probes in total. The data is seeded, and a rerun replaces it.
`scripts/silence_baseline_demo.py` runs the checks below.

**The per-household check works as intended.** Two new probes, both answered
after 30 minutes, each judged against that household's earlier probes:

| Household | Its baseline | 30-min answer |
|---|---|---|
| Fast responder (median 87 s) | late after 3.7 min | **late** (z +9.8) |
| Slow responder (median 35 min) | late after 71.8 min | **normal** (z −0.7) |

The fast responder still silent after 10 minutes is also flagged late
(z +5.7).

**Held-out comparison** against one threshold for everyone, the 99th
percentile of all training responses (late after 84 min):

| | Personal baseline | One threshold for everyone |
|---|---|---|
| Injected late responses at 10× own median, caught | 24/24 (fast households 13/13) | 12/24 (fast households 1/13) |
| Injected late responses at 3× own median, caught | 13/24 | 6/24 |
| Normal held-out responses flagged late | 0/221 | 0/221 |

## What this test does and does not show

- **It validates detection sensitivity only.** The personal baseline catches
  lateness that a one-size threshold misses, especially for fast responders.
  That follows from the method, and the test confirms the code implements it.
- **It is not evidence that the personal baseline reduces false positives.**
  Both rules flag 0 of 221 normal responses because the synthetic latencies
  are drawn from clean log-normal distributions, which a robust log-scale
  rule fits by construction. Real response times have habits these
  distributions do not model: sleep, work shifts, dead phones, weekends. The
  spec's claim that this baseline is the silence engine's biggest
  false-positive reducer is **untested**; the "0/221 for both" result does
  not bear on it.
- Testing the false-positive claim needs real probe histories from a
  registry, or at least realistic non-log-normal synthetic patterns.
