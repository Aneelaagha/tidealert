# Load test

Measured on 2026-10-04 with `scripts/load_test.py`. Every number below is
measured, not estimated. The raw reports (each request's latency and status,
summarised per endpoint) are the JSON files in [`docs/load-test/`](load-test/).

## Headline

| Pass (60 s each) | 1 worker (current config) | 4 workers |
|---|---|---|
| **Full dashboard, target load** (30 dashboards + 150 field clients) | **fails badly**: `/map/zones` p95 14.4 s; even `/tasks` p95 13.1 s | **near pass**: `/map/zones` p95 1.56 s ✓, `/map/freshness` 481 ms ✓, `/tasks` 509 ms ✗ (by 9 ms), `/cases` 715 ms ✗ |
| Full dashboard, 2× | fails, with 30 s timeouts | fails: `/map/zones` p95 4.4 s |
| Full dashboard, 4× | fails, with timeouts and refused connections | fails: about 30 s p95 everywhere |
| **Panels only, target load** | **passes**: `/tasks` p95 116 ms, `/cases` 129 ms | **passes**: 81 ms, 105 ms |
| **Copilot, template mode** (30 users) | **passes**: p95 89 ms | **passes**: p95 95 ms |
| **Writes, ordinary dispatching** (5 dispatchers) | **passes**: assign p95 51 ms | **passes**: assign p95 45 ms |
| **Writes, race** (10 concurrent assigns of one task) | **fails: 4–5 of 10 succeed** | **fails: 3–10 of 10 succeed** |

Two findings:
1. **Concurrent assigns of one task can all succeed.** One task gets assigned
   to several responders. This was spotted by reading the code before any
   test ran, and the test proves it. It's a correctness bug, not a
   performance one, and the fix is its own PR.
2. **`/map/zones` is the bottleneck.** At the target load, one worker can't
   keep up, and every other request queues behind it. Four workers bring
   `/map/zones` inside its bar at 1×. But the panel reads still just miss
   theirs under the full dashboard mix, and everything fails at 2×. So
   worker count is a large part of the problem (about 9× better at p95),
   but not all of it. Each refresh rebuilds about 690 kB (gzipped) of zone
   GeoJSON per request, and that per-request cost is architectural.
   Caching zones per run and time would attack it directly. Not built: it
   would be a separate PR.

## Setup

- **Machine:** Apple M4, 10 cores, 24 GB.
- **Database:** Postgres/PostGIS 16 in Docker on the same machine (no network
  latency between app and database).
- **Load generator:** the same machine, competing for CPU.
- **Server:** `uvicorn app.main:app`, either 1 worker (the current config) or
  `--workers 4`. Database pool: SQLAlchemy's default, 5 + 10 overflow, so
  15 connections per worker. No model key: the copilot runs in template
  mode.
- **Data:**
  - Reads: Harvey (`backtest:2017-08-25..2017-09-02`) at 2017-08-27 18:30
    (152 tasks, 133 cut off). Real data, read-only.
  - Writes: **only the mixed run.** The script refuses to write anywhere
    else. It adds temporary "Load-test responder N" rows to the mixed run,
    then acts through the real task endpoints.
  - **Cleanup:** after each writes pass, `scripts/mixed_harvey_scenario.py`
    rebuilt the mixed run. A full snapshot (Cases, contributions, every
    task's event history, responders) was **byte-identical** to the one
    taken before testing, both times, with no load-test responders left.
    Harvey, the scenarios and the 161-Case baseline weren't touched.
- **Single-request baselines** (medians, Harvey at 18:30, idle server):
  `/tasks` 29 ms, `/cases` 43 ms, `/map/freshness` 8 ms, `/responders` 3 ms,
  `/copilot/ask` (template) 21 ms, `/map/zones` **714 ms** (688 kB gzipped).

## What each simulated user does

- **Dashboard:** every 15 s, it replays a slider stop: `/map/zones` and
  `/map/freshness` together, then `/tasks` and `/cases` together. That's
  what the page requests.
- **Field client:** `/tasks` every 30 s.
- **Panels-only dashboard:** `/tasks` and `/cases` every 15 s, an open page
  with no slider change.
- **Copilot user:** a question every 10 s, cycling through the five intents
  and a free-text question.
- **Dispatcher:** works through its own tasks in turn. For each: clear-verify
  if flagged, assign to its responder, mark complete.
- **Race:** 5 tasks. For each, 10 concurrent assigns with 10 different
  responders.

Start offsets are spread with a seeded generator (seed 7), so runs repeat.
A cycle that overruns starts the next one immediately. Those are counted as
"late cycles" in the reports.

## Targets: where the numbers come from

- **~150 field clients:** Harvey's peak has 152 tasks. One field team per
  task, each device polling `/tasks` every 30 s. **This stays a stated
  assumption.** The sourced check below doesn't give a per-incident device
  count.
- **~30 dispatcher and supervisor dashboards:** the Incident Command System's
  span of control is 3–7 per supervisor, typically 5. That's a citable ICS
  standard, applied here to about 150 field teams.
- **Stress:** 2× and 4× the target. 4× is 120 dashboards, more than the
  Harris County EOC's reported 98 workstations (below).

**Sourced check** (10 minutes, as agreed; not a full staffing study):
- **Confirmed:** FEMA, *Historic Disaster Response to Hurricane Harvey in
  Texas* (22 September 2017): *"FEMA assigned 28 Urban Search and Rescue
  (USAR) teams … to deploy to Texas … The teams rescued 6,453 people."*
  <https://www.fema.gov/print/txt/node/316408>. This is statewide and
  counts teams, not devices, so it corroborates the order of magnitude (tens
  of teams) but not the 150 figure.
- **Unverified, second-hand:** the Harris County Harvey after-action
  coverage reportedly describes an EOC with **98 workstations** and **about
  50 full-time staff**. I saw this in a search summary of HSToday's article,
  but the article itself returned HTTP 403, and Gov1's copy doesn't include
  those details. If true, it supports 30 dashboards as plausible, and 4× as
  a real ceiling. It's treated as unverified.
- **Verdict:** the dashboard count is consistent with what I could find. The
  field-client count **remains an assumption**.

## Pass bars

| Measure | Bar | Why |
|---|---|---|
| Panel reads (`/tasks`, `/cases`, `/map/freshness`, `/responders`) | p50 ≤ 150 ms, **p95 ≤ 500 ms** | baselines 3–43 ms. 500 ms keeps a poll well inside the ~1 s point where people notice a delay (Nielsen's 0.1 s / 1 s / 10 s guidance). |
| `/map/zones` | **p95 ≤ 3 s** | baseline 714 ms. The page already shows "loading…" on a slider stop; 3 s is about 4× the baseline. |
| Task actions | **p95 ≤ 500 ms**, and **exactly one success per raced task** | correctness can't be traded for speed. |
| Copilot (template) | **p95 ≤ 1 s** | baseline 21 ms. |
| Errors | **0 server errors, 0 timeouts, 0 refused connections** | 409 and 422 refusals are counted as correct answers. |

These bars are my choice, grounded in the baselines and that guidance. They
are not an SLA.

## Results in full (p95, with p50 in brackets; ✓/✗ against the bar)

### 1 worker
| Pass | `/map/zones` | `/map/freshness` | `/tasks` | `/cases` | errors |
|---|---|---|---|---|---|
| Dashboard 1× | 14.4 s (10.5 s) ✗ | 13.0 s ✗ | 13.1 s (8.6 s) ✗ | 11.7 s ✗ | 0, but 76 late cycles |
| Dashboard 2× | 30.0 s ✗ | 30.0 s ✗ | 30.0 s ✗ | 29.1 s ✗ | 99 timeouts, 1 read error |
| Dashboard 4× | 31.1 s ✗ | 31.1 s ✗ | 33.9 s ✗ | 32.0 s ✗ | 676 timeouts, 1,022 refused connections |
| Panels 1× | — | — | 116 ms (69 ms) ✓ | 129 ms (87 ms) ✓ | 0 |
| Copilot | — | — | — | — | 0; `/copilot/ask` p95 89 ms (48 ms) ✓ |

### 4 workers
| Pass | `/map/zones` | `/map/freshness` | `/tasks` | `/cases` | errors |
|---|---|---|---|---|---|
| Dashboard 1× | **1.56 s (834 ms) ✓** | **481 ms ✓** | **509 ms (55 ms) ✗** | **715 ms (79 ms) ✗** | 0 |
| Dashboard 2× | 4.4 s ✗ | 2.2 s ✗ | 2.4 s ✗ | 2.7 s ✗ | 0 |
| Dashboard 4× | 30.4 s ✗ | 25.3 s ✗ | 30.5 s ✗ | 30.4 s ✗ | 1 read error; 287 late cycles |
| Panels 1× | — | — | 81 ms (56 ms) ✓ | 105 ms (73 ms) ✓ | 0 |
| Copilot | — | — | — | — | 0; p95 95 ms (52 ms) ✓ |

At 4 workers and 1×, the panel reads' **medians** are fine (55 ms and 79 ms).
It's the tail, the requests that land behind a `/map/zones` build, that
misses.

### Writes (both configs)
| | 1 worker | 4 workers |
|---|---|---|
| assign (142 calls) | p95 51 ms ✓ | p95 45 ms ✓ |
| clear-verify (147) | p95 47 ms ✓ | p95 44 ms ✓ |
| complete (142) | p95 53 ms ✓ | p95 36 ms ✓ |
| **race: successes out of 10, per task** | **5, 4, 4, 4, 4 ✗** | **10, 4, 3, 3, 5 ✗** |

In every race, the task's history recorded as many "assigned to …" events as
there were successes: **one task was assigned to several responders at
once.** The cause: `task_actions.assign` reads the task's status, checks it
and writes, with no row lock (`SELECT … FOR UPDATE`) or conditional update.
Concurrent requests all see "pending".

**That it got worse with more workers matters.** Up to 10 of 10 succeeded at
4 workers, against 4–5 at 1. That shows a true cross-process race in the
database, not something a single worker's Python execution was partly
hiding. More processes means more requests reading "pending" before any of
them writes. The fix has to be in the database: lock the row. Serialising in
Python wouldn't work across processes.

## What this does and doesn't show

**It shows:**
- how this code behaves under a stated concurrent load, on Harvey's real
  data, on one machine;
- that `/map/zones` is the bottleneck;
- that worker count is a large part of the problem, but not all of it;
- that panel polling, the copilot's template path and ordinary dispatching
  all hold up at the target load on either config;
- **a real concurrency bug in assign.**

**It doesn't show:**
- **Performance on any deploy target.** The database here is local, with no
  network latency between app and database, and the load generator shares
  the CPU. A different machine, a remote database, a proxy or a different
  worker count all need a rerun. The script is committed for that.
- **Bigger regions.** `/map/zones` grows with the number of zones (Harvey:
  6,049).
- **Model-mode copilot under load.** It wasn't tested: it needs a key, every
  call costs money, and the API provider's own rate limits would dominate.
  The per-IP limiter only applies to model mode, so it didn't engage here.
- **Live mode,** which doesn't exist, or the cost of authentication (there
  isn't any).
- **Real people.** The user counts are a stated derivation, not a measured
  incident.

**About the numbers:** the client timeout is 30 s *per operation* (httpx
connect, read and write each), so a request that keeps receiving data can
run past 30 s in total. That's why some maxima exceed 30 s.

## Known follow-ups

- **The assign race:** its own PR. Lock the task and responder rows
  (`SELECT … FOR UPDATE`) in `assign`, `set_status` and `clear_verify`, then
  rerun the race pass on both configs, expecting exactly 1 of 10.
- **The `/map/zones` bottleneck: not fixed here, a documented gap.** The
  likely directions are caching the zone GeoJSON per run and time (every
  dashboard viewing the same time would share one build), running more
  workers, or both. It's a larger piece that needs its own plan, and it
  shouldn't be tangled with the race fix. Until then, the current 1-worker
  config can't serve 30 dashboards doing full refreshes every 15 s. It can
  serve panel polling at the target load.

## Reproducing it

From the repo root, with the API running on port 8010 (with `--workers 4`
for the 4-worker runs):

```bash
.venv/bin/python scripts/load_test.py dashboard --dashboards 30 --field 150 --duration 60 --out docs/load-test/1w-dashboard-1x.json
.venv/bin/python scripts/load_test.py dashboard --dashboards 60 --field 300 --duration 60 --out docs/load-test/1w-dashboard-2x.json
.venv/bin/python scripts/load_test.py dashboard --dashboards 120 --field 600 --duration 60 --out docs/load-test/1w-dashboard-4x.json
.venv/bin/python scripts/load_test.py panels --dashboards 30 --field 150 --duration 60 --out docs/load-test/1w-panels-1x.json
.venv/bin/python scripts/load_test.py copilot --users 30 --duration 60 --out docs/load-test/1w-copilot.json
.venv/bin/python scripts/load_test.py writes --dispatchers 5 --races 5 --race-width 10 --duration 60 --out docs/load-test/1w-writes.json
.venv/bin/python scripts/mixed_harvey_scenario.py   # always, after a writes pass: rebuilds the mixed run
```
