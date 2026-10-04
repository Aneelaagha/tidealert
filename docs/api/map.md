# Map API and page

**Running it:** start the API from `backend/` with
`../.venv/bin/uvicorn app.main:app`, then open `/` (it redirects to `/ui/`).

This API is read-only. Code: `backend/app/routes/map.py` and
`backend/app/services/map_state.py`. Tests: `tests/test_map_api.py`, which
run against the local database; the fixture docstring lists the runs they
need.

| Endpoint | Returns |
|---|---|
| `GET /runs` | Every run: mode (as registered, never inferred), window, regions, extent, sources, caveats, and `task_actions_blocked` (the exact reason the task actions refuse this run, or null). Also `vocabulary`: every value the map can be styled by, taken from the enums and the stored coverage gaps. |
| `GET /map/zones?run_id=&at=&bbox=` | GeoJSON of the run's zones as of `at`. Coverage-gap reason texts are listed once in `gap_reasons` and referenced by `reason_id`. |
| `GET /map/freshness?run_id=&at=` | For each source the run reads: `fresh` / `stale` / `no_data` / `event_driven`, with the last observation and its age. |
| `GET /cases?run_id=&zone_id=&at=` | The run's Cases opened by `at`, with contributions and confidence as of `at`, and their tasks as of `at` (with event history). |
| `GET /tasks`, `GET /tasks/{id}`, `GET /responders`, and the task actions | See [task-lifecycle.md](../algorithms/task-lifecycle.md). |

## Time

- **What `at` is:** the run's clock, not the wall clock.
- **Replay or scenario:** `at` must lie inside the run's window and include a
  timezone. It defaults to the end of the window.
- **Live:** `at` defaults to now.
- **Nothing from after `at` is shown:**
  - Cases opened after `at` are left out.
  - Contributions first observed after `at` are left out.
  - Case confidence is recomputed as of `at`.

**Check against the live sweeps:** reading the Harvey run back at each of its
865 ticks reproduces the confidence word the live sweep set at that tick, for
all 99,699 Case-ticks.

## What a zone carries

- **`risk_level`:** the stored value, shown only once it was set by `at`
  (`risk_level_set_at`). Before that the zone reads `unknown`, with a
  `risk_level_note`. It never shows a value from the zone's future, and
  `unknown` is never shown as `safe`.
- **`data_confidence`:** null means "not assessed". No engine computes it yet.
- **`coverage_gaps`:** each gap has a kind, a status and a reason.
  - A time-bound gap (for example "possibly isolated" from a stage onward)
    becomes `active` at its `since` time.
  - A permanent gap (for example isolation not evaluated, for a block cut off
    from the road network even with every road dry) is always active.
- **Case summary:**
  - `case_count`;
  - the strongest `confidence_word` among the zone's Cases, in the order
    corroborated > single_source > stale_verify (all Cases are listed in
    `/cases`);
  - the engines with supporting evidence, as `engines` and as
    `engine_<name>` flags.

- **Task summary as of `at`**, from `task_events`:
  - `task_count`: tasks active at `at`;
  - `task_awaiting`: of those, pending and not flagged (assignable now);
  - `task_flagged`: of those, flagged verify before dispatch;
  - `task_status`: the most advanced (en_route > assigned > pending);
  - `task_priority`: the highest;
  - `task_verify`: whether any is flagged for verification;
  - `task_kinds`;
  - `task_anchor`: a point inside the zone (`ST_PointOnSurface`), present
    only when a task is active.

Every zone in the run's regions is returned, with or without a Case.

## Freshness

- **Rule:** a source is `stale` when `at` minus its last observation is more
  than `stale_after_seconds`. The run's override (`run_sources`) takes
  precedence over the source's own value.
- **Event-driven sources** (cadence 0, e.g. household replies) are reported
  with their age but never judged fresh or stale.
- **Runs that read no source recorded as signals** (the synthetic silence
  scenario) get a note that freshness is not tracked.

## Known limitations

- **Only the latest `risk_level` is stored.** A zone raised to `elevated` and
  later to `extreme` reads `unknown` before the second raise, not
  `elevated`.
- **Case status has no history.** It is the current status, whatever `at` is.
- **Refreshed evidence keeps only its last confirmed value.** Read back at an
  earlier time, it carries that last value, not the value it had then.
- **No live run exists yet**, so `live` mode is not exercised.
- **Size:** `/map/zones` for the Harvey run is about 5 MB of GeoJSON (about
  650 kB gzipped).

## Page (`frontend/`)

A React + TypeScript app built with Vite and styled with Tailwind, using
MapLibre GL JS 4.7.1 from npm.

**Running it:**
- **Built:** in `frontend/`, run `npm install` then `npm run build`. FastAPI
  serves `frontend/dist` at `/ui/`. If `dist` doesn't exist, `/ui/` says how
  to build it. `dist` is not committed.
- **Development:** run `npm run dev` (Vite, with hot reload). It proxies the
  API paths to `http://127.0.0.1:8000`, or to `TIDEALERT_API` if set.
- **Checks:** `npm run lint` (TypeScript) and `npm test` (vitest).

**Where things are:**
- `src/lib/api.ts` is the only code that talks to the backend.
- `src/lib/colors.ts` is the only value-to-color table.
- `src/lib/time.ts` holds the run clock and the URL state.

The look (dark theme, panels, grid texture, radar sweep) is adapted from a
design reference. None of the reference's data, simulation or copilot was
carried over.

**What it shows:**
- **Header:** a run picker with a mode badge taken from `runs.mode`, and a
  time slider over the run's window, stepping every 15 minutes (the sweep
  cadence).
- **Freshness banner** with the run's caveats.
- **Map,** with a status line counting zones, Cases, tasks and coverage
  gaps.
- **Zone panel:** the zone's Cases and contributions from `/cases`. A
  contribution's text is labelled "recorded when first observed", since it
  can differ from the refreshed confidence next to it.
- **Legend.**
- **Cases panel** (from `/cases` as of the slider time): each Case's
  confidence word, zone, status, opened time, supporting engines and active
  task. Filter tabs: open (open and in progress), closed (resolved and false
  alarm), and all. Strongest word first, then oldest. Selecting a Case
  selects its zone and opens its task actions.
- **Responders panel** (from `/responders`, plus `/tasks` for assignments):
  name, role, team, last ping, location (none recorded today) and the
  active tasks assigned as of the slider time. The status shown is the
  responder's **current** status: the database keeps no history of it. A
  run with no responders says so.
- **Copilot panel:** questions about the run as of the slider time, from
  `/copilot/status` and `/copilot/ask`. See
  [docs/algorithms/copilot.md](../algorithms/copilot.md#panel-map-page).
- **Footer feed:** the run's task events up to the slider time, newest
  first, from `/tasks`. Each entry is a stored event with its own time,
  actor and note.

**Where the map's content comes from:**
- **Shapes:** zone outlines from the database geometry.
- **View:** fitted to the run's extent from `/runs`.
- **Styles:** fill comes from `risk_level`. The outline comes from the
  zone's strongest confidence word (dashed for `stale_verify`). Active
  coverage gaps are hatched with a dashed edge.
- **Colors:** `COLORS` in `src/lib/colors.ts` is the only value-to-color
  table. A value with no entry draws in magenta and is flagged in the legend
  as an unstyled value.
- **Shareable views:** the run and time are kept in the URL (`?run=&at=`).
- **Task markers:** one circle per zone with an active task, at the zone's
  `task_anchor`.
  - **Fill** is the most advanced status among the zone's active tasks
    (`pending` is hollow white, `assigned` blue, `en_route` green).
  - **A thick amber edge** means at least one of the zone's active tasks is
    flagged verify before dispatch.
  - **Size** is the highest priority.
  - **Closed statuses** are set to `null` in `COLORS`: deliberately not
    drawn, and the legend says so. A status with no entry at all still
    draws magenta.
  - **The status line counts tasks**, not zones (`task_awaiting`,
    `task_flagged`).
  - **The zone panel** lists each Case's tasks as of the slider time, with
    the assignee and the full event history.
- **Decoration:** the grid texture, the radar sweep and the "Sound test"
  tone (muted until sound is turned on) are decoration only. No data drives
  them, and they show no values.

**Task actions (assign, mark complete):**
- **Where they run:** on scenario and live runs only. On a replay, the
  buttons are greyed out and the operator bar shows the server's own refusal
  reason from `/runs` (`task_actions_blocked`), the same text the actions
  return.
- **Who acted:** an operator name is required, because there's no login and
  every event records who acted. The browser remembers it (`localStorage`).
- **When:** each action is stamped with the slider time; on a live run it's
  omitted and the server uses now. The server refuses a time before the
  task's latest event.
- **Greyed-out buttons:** a button is greyed out with its reason only when
  the server would certainly refuse:
  - assign needs a pending, unflagged task and an available responder;
  - complete needs an assigned or en-route task;
  - a task flagged verify before dispatch shows the stored note that set
    the flag (clearing it is API-only).

  Otherwise the server decides. Any 409 or 422 is shown exactly as
  returned, for example `HTTP 422: at … is before the task's latest event
  (…)`.
- **After an action** the page reads everything again: zones, Cases, tasks
  and responders.
- **Side effect on the demo data:** actions write real rows. An assign adds
  a task event, sets the responder to assigned and moves an open Case to
  `in_progress`. A complete adds an event and frees the responder. The
  Case's status is left as it is: resolving a Case is a person's call. So
  trying the actions on the listening or silence scenario changes that
  scenario until it's rerun (`scripts/listening_demo.py`, or the silence
  sweep in `scripts/run_case_matcher.py`). The "161 Cases unchanged" check
  fails until then. Automated tests act only inside rolled-back
  transactions.

**No invented data, enforced:** `src/test/no-invented-data.test.ts` is a
permanent part of the test suite. It scans every source file and fails if
it finds any of these:
- `Math.random`;
- the wall clock (`Date.now()`, `new Date()`) used as a value;
- a `fetch` outside `src/lib/api.ts`;
- an outside host other than the basemap tiles;
- a hardcoded list of records;
- any of the design reference's invented concepts or its persona;
- a model SDK (Gemini, OpenAI, Anthropic), Express or dotenv in
  `package.json`, or a `server.*` file. The copilot is `/copilot/ask` only.

It's a lexical check: it catches those patterns, not every possible way to
fake a value.

**Page limitations:**
- **Basemap:** tiles come from OpenStreetMap's public tile server, darkened
  in the style. That's fine for development, but a deployment needs its own
  tile source or one allowed by OSM's tile usage policy.
- **Engines on the map:** contributing engines appear only in the zone
  panel, not as map symbols.
- **Only assign and complete:** clear-verify, en route, unable to reach,
  cancel and follow-up tasks are API-only
  (`docs/algorithms/task-lifecycle.md`).
- **Case status has no history:** after an assign, a Case reads "in
  progress" even when the slider is moved back to before the assignment.
  The task's own status is shown correctly as of the slider time.
- **No responder markers:** no responder has location data (the API
  exposes only `has_location`, and it's false for all of them). Markers can
  come once locations are populated.
- **One marker per zone:** a zone's marker summarizes all its active tasks.
  The zone panel has the detail.
- **Slider step:** the 15-minute cadence is assumed in `src/lib/time.ts`; a
  run doesn't store its cadence.
- **Each slider stop refetches every zone:** the full zone GeoJSON, about
  650 kB gzipped and about 0.8 s for Harvey. Keyboard stepping commits once
  the keys pause for 400 ms, not on every key press.
- **Bundle size:** about 1 MB minified (about 300 kB gzipped), most of it
  MapLibre.
- **Synthetic scenarios** place their blocks near lat/lon 0, on open water
  in the basemap.
- **No live mode test:** no live run exists, so the LIVE badge and the
  slider-less live view are untested.
