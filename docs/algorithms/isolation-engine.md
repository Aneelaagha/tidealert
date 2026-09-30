# Isolation engine

When does a neighborhood lose every road route out during a flood, and how
much warning does that give compared with simply watching the river gauge?

The only site input is a USGS gauge ID:

```bash
.venv/bin/python scripts/run_isolation_pipeline.py 08074500
```

Code: `scripts/run_isolation_pipeline.py` (pipeline and backtest report) and
`backend/app/services/` (`gauge_site`, `terrain`, `stage`, `ingest`,
`street_blocks`, `isolation_engine`, `fim_library`, `sentinel1`, `rainfall`,
`nfip`, `census`).

## Current validated result

> **At both gauges with an NWS flood-map library, the first road flooded by
> the river driver comes 37–75 minutes before the gauge reaches its NWS
> minor flood stage** (Greens Bayou +37 min, White Oak Bayou +75 min, Hurricane
> Harvey 2017). This matches the earlier, independently built flood-map-only
> engine's +77 min estimate for White Oak Bayou.

That is the only result this engine currently treats as validated. Whole-zone
isolation arrives **after** the gauge alarm at both NWS-map gauges, so on its
own it adds no warning over watching the gauge:

| Harvey 2017, river driver only | White Oak Bayou 08074500 | Greens Bayou 08076000 | Hunting Bayou 08075770 |
|---|---|---|---|
| River flood source | NWS flood map (HGTT2) | NWS flood map (GBHT2) | HAND, **lower confidence** |
| Minor-flood alarm | 2017-08-26 23:29 CDT | 2017-08-26 10:21 CDT | 2017-08-27 05:05 UTC (**fallback threshold**) |
| First road floods | **+75 min** | **+37 min** | +1026 min (unverified) |
| First zone isolated | −150 min | −863 min | +6 min |
| First zone stranded dry | −315 min | −863 min | +6 min |
| HAND vs NWS map, IoU over flooding steps | median 0.64 (0.58–0.84) | median 0.70 (0.27–0.77) | n/a |
| Evaluated / unknown zones | 1,667 / 1,843 | 581 / 911 | 596 / 421 |

`+` means before the alarm. Timesteps are 15 minutes. Hunting Bayou's numbers
use a percentile fallback threshold and HAND. They show the pipeline runs with
no manual tuning on a gauge without NWS products, not a validated lead time.
Hunting's first-road signal is physically consistent (road ground 1.18 m below
the gauge's water surface, 450 m downstream) but unconfirmed: no flood map
exists, and channel walls or the IH 610 overpass may not be resolved at 10 m.

## Pipeline

Everything below is derived from the gauge ID; nothing is set by hand per site.

| Input | Source |
|---|---|
| COMID, location | NLDI crosswalk (`nwissite/USGS-{site}`) |
| Study area | NLDI upstream drainage basin |
| Flood thresholds | NWS NWPS categories. Missing categories fall back to percentiles of USGS annual peak stages (p50 minor, p80 moderate, p90 major). The fallback is logged as a warning and printed as `*** FALLBACK, NOT AN NWS THRESHOLD ***` |
| Gauge datum, time zone | USGS monitoring location, NWS NWPS |
| Stage | USGS 15-min gage height; gaps filled from USGS discharge (including ESTIMATED values, stored as `inferred`) through the event's own rating curve |
| River flooding | NWS flood-map library where published, otherwise HAND (below) |
| Roads | OSM drivable network inside the basin, as of the day before the event (Overpass historical query, logged with fetch timestamps) |
| Zones | OSM street blocks (faces of the road network) with 2020 census population. Blocks with no residents are dropped |
| Claims | OpenFEMA NFIP claims (v3) for the zones' counties, joined by census block group |
| Validation | HAND vs NWS map agreement (every run), Sentinel-1 RTC change detection (Planetary Computer) |

### River driver

Each road is sampled every 5 m and floods when at least 2 samples (~10 m) are
wet.

- **NWS flood map (primary).** A sample floods when the library layer in
  effect covers it. The layer in effect is the next library stage up from the
  gauge stage, which is NWS's own convention for its category maps. Nothing
  floods below the lowest library stage. The driver only covers the map's
  largest mapped extent. Outside it the map says nothing, so roads draining to
  the river outside that extent are unknown, even near the gauge.
- **HAND (only where NWS publishes no library; lower confidence).** A sample's
  height above nearest drainage is the highest ground on its flow path down to
  the channel, minus the channel elevation. Water must overtop that ground to
  reach the sample, so the height is never negative. Channel elevations are
  snapped to the lowest ground within 30 m, because the rasterized NHDPlus
  flowline sits on the bank for about half the mainstem (47% of White Oak's
  mainstem cells are more than 1 m above the lowest ground within 30 m). HAND
  assumes constant water depth along the reach. It only covers cells draining
  to the gauge's own NHDPlus reach. The caveat is printed, stored in the report
  JSON, and written to every evaluated zone's `coverage_gaps`.

HAND vs NWS agreement is computed on every run for every gauge that has a
library, both per library stage and at every flooding timestep. It is an
ongoing validation metric, not a one-off check.

### Isolation

The main network is the largest connected component of the unflooded road
graph. A zone (street block) is reachable while at least one road on its
boundary is dry and part of the main network, and isolated when none is.
An isolated zone is "stranded" when some boundary road is still dry but cut
off, and "submerged" when all of them are flooded. Each zone's countdown to
isolation, as of the gauge's minor-flood alarm, is written to
`zones.isolation_minutes`.

Zones are not evaluated, and get no countdown, when:

- **unknown:** a boundary road drains to river the flood source does not
  cover. The reason is recorded in `zones.coverage_gaps`.
- **not connected at base flow:** the block's roads do not reach the main
  network even with every road dry (network fragments, basin-boundary cuts).

### Standing checks

Before any isolation run, the pipeline fails loudly
(`BaseFlowFloodingError`) unless, at the first timestep:

- the gauge is below minor flood stage,
- zero road segments are flooded, and
- zero evaluated zones are isolated.

These checks exist because two earlier versions of this engine reported
flooding at base flow that came from modeling errors, not from the event.

## Known limitations

### Unknown roads are treated as passable

**This is the riskier default for a safety tool.** Roads whose flooding the
engine cannot determine (outside the flood source's coverage) are kept in the
road graph as passable when computing routes for evaluated zones. A zone
whose only real exit runs through an unknown, actually flooded road can
therefore be reported reachable. The share of such roads is printed on every
run: 44.5% of White Oak Bayou's basin roads, 54.5% of Greens Bayou's and 37.5%
of Hunting Bayou's in the Harvey backtest. Treating unknown roads as blocked,
or reporting reachability as a range, is open work.

### Rain driver: not yet validated, no output

A direct-rainfall ponding driver exists in the code (`app.services.rainfall`
and the rain paths of `isolation_engine`). It works like this:

- AORC hourly rainfall per NHD catchment.
- Drain capacity from the NOAA Atlas 14 2-year 1-hour rainfall, set to 0
  while the gauge is above minor flood stage.
- Ponding capped at the receiving river level, and limited to closed
  depressions where that level is unmeasured.

It is **gated off** (`RAIN_DRIVER_VALIDATED = False`): the engine refuses to
run it and the pipeline produces no rain-driven isolation output. In the Harvey
backtest it over-predicted flooding in every basin:

- only 3–7% of its modeled water was confirmed by Sentinel-1,
- every evaluated Greens Bayou zone ended up isolated.

Calibrating the depression-filling rule against Sentinel-1 comes before any of
its numbers are reported. AORC rainfall is still ingested as input data.

### Other limitations and assumptions

- **Tunnels are not exempt from flooding.** Spec §2 exempted bridges and
  tunnels from terrain-based flood removal. Only bridges are exempt here: they
  are elevated above the flood surface. Tunnels and underpasses are below grade
  and flood first, a known Houston hazard. This is a deliberate, corrected
  deviation from the spec.
- **Coverage is small.** The NWS libraries cover 2.53 km² (White Oak) and
  6.76 km² (Greens) of their basins, so most residents are in unknown zones.
- **Coarse claims timing.** NFIP claims only carry a date of loss, so lead
  times against claims are ranges over a whole day. For gauges without an NWS
  record the time zone falls back to UTC (logged), shifting day boundaries.
- **Stage gaps.** They are filled through a rating curve that ignores
  hysteresis (White Oak Bayou: 426 of 865 steps, because the gauge stopped
  recording stage at the Harvey peak).
- **Fallback thresholds can mix datums.** Annual peak series can span
  gauge-datum changes, which the percentile fallback does not correct for.
- **Undirected road graph.** One-way rules are ignored (rescue vehicles).
- **Sentinel-1 misses urban flooding.** Water among buildings raises radar
  backscatter, so low confirmation rates partly reflect the sensor, not only
  the model.
