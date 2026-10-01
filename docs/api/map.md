# Map API and page

**Running it:** start the API from `backend/` with
`../.venv/bin/uvicorn app.main:app`, then open `/` (it redirects to `/ui/`).

This API is read-only. Code: `backend/app/routes/map.py` and
`backend/app/services/map_state.py`. Tests: `tests/test_map_api.py`, which
run against the local database; the fixture docstring lists the runs they
need.

| Endpoint | Returns |
|---|---|
| `GET /runs` | Every run: mode (as registered, never inferred), window, regions, extent, sources, caveats. Also `vocabulary`: every value the map can be styled by, taken from the enums and the stored coverage gaps. |
| `GET /map/zones?run_id=&at=&bbox=` | GeoJSON of the run's zones as of `at`. Coverage-gap reason texts are listed once in `gap_reasons` and referenced by `reason_id`. |
| `GET /map/freshness?run_id=&at=` | For each source the run reads: `fresh` / `stale` / `no_data` / `event_driven`, with the last observation and its age. |
| `GET /cases?run_id=&zone_id=&at=` | The run's Cases opened by `at`, with contributions and confidence as of `at`. |

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

## Page (`frontend/index.html`, `frontend/map.js`)

Plain HTML/JS with MapLibre GL JS 4.7.1 from jsDelivr, served by FastAPI
`StaticFiles` at `/ui/`. There's no build step.

**What it shows:**
- a run picker with a mode badge taken from `runs.mode`;
- a time slider over the run's window, stepping every 15 minutes (the sweep
  cadence);
- the freshness banner with the run's caveats;
- the legend;
- a zone panel with that zone's Cases and contributions from `/cases`.

**Where the map's content comes from:**
- **Shapes:** zone outlines from the database geometry.
- **View:** fitted to the run's extent from `/runs`.
- **Styles:** fill comes from `risk_level`. The outline comes from the
  zone's strongest confidence word (dashed for `stale_verify`). Active
  coverage gaps are hatched with a dashed edge.
- **Colors:** `COLORS` in `map.js` is the only value-to-color table. A value
  with no entry draws in magenta and is flagged in the legend as an
  unstyled value.
- **Shareable views:** the run and time are kept in the URL (`?run=&at=`).

**Page limitations:**
- **Basemap:** tiles come from OpenStreetMap's public tile server. That's
  fine for development, but a deployment needs its own tile source or one
  allowed by OSM's tile usage policy.
- **Engines on the map:** contributing engines appear only in the zone
  panel, not as map symbols.
- **Slider step:** the 15-minute cadence is assumed in `map.js`; a run
  doesn't store its cadence.
- **Each slider stop refetches every zone:** the full zone GeoJSON, about
  650 kB gzipped and about 0.7 s for Harvey.
- **Synthetic scenarios** place their blocks near lat/lon 0, on open water
  in the basemap.
- **No live mode test:** no live run exists, so the LIVE badge and the
  slider-less live view are untested.
