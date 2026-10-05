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

## Results (Hurricane Harvey 2017)

### Primary result: first flooded road

> **At both gauges with an NWS flood-map library, the first road flooded by
> the river driver comes 37–75 minutes before the gauge reaches its NWS
> minor flood stage** (Greens Bayou +37 min, White Oak Bayou +75 min). This
> matches the earlier, independently built flood-map-only engine's +77 min
> estimate for White Oak Bayou.

This is the result the engine currently treats as validated and reportable.

The numbers use NWS's own convention for its category maps: a stage uses the
next library layer **up**. If a layer only applied once the stage actually
reached it (round-down), the leads shrink to +22 min (Greens) and +60 min
(White Oak). Both conventions give a lead ahead of the gauge alarm.

| First road floods, vs minor-flood alarm | NWS convention (round-up) | Round-down |
|---|---|---|
| White Oak Bayou 08074500 | **+75 min** | +60 min |
| Greens Bayou 08076000 | **+37 min** | +22 min |

### Secondary result: first confirmed zone isolation (White Oak only)

Smaller and more caveated. At White Oak Bayou, whole street blocks become
**confirmed isolated** (isolated even if every road of unknown status is
passable) before the gauge alarm:

| First confirmed zone isolation, vs minor-flood alarm | NWS convention (round-up) | Round-down |
|---|---|---|
| White Oak Bayou 08074500 | +30 min | +15 min |

- **Mechanism.** The first such block (29 residents, 7,300 m²) has four
  boundary roads, all dry. It is cut off (stranded) because every route
  from them to the main road network crosses roads the NWS map floods at its
  30.7 ft layer. At the time the stage was 30.29 ft, below the 32 ft minor
  flood stage.
- **Scale.** 3 street blocks, 68 people, are confirmed isolated at or
  before the alarm, under either convention.
- **Why it is new.** These blocks touch roads whose flooding is unknown.
  Earlier versions excluded such blocks. Bounded reachability (below)
  now evaluates them.

At Greens Bayou the first confirmed isolation comes 863 min *after* the
alarm, so there whole-zone isolation adds no warning over watching the gauge.

### All three gauges

| River driver only | White Oak Bayou 08074500 | Greens Bayou 08076000 | Hunting Bayou 08075770 |
|---|---|---|---|
| River flood source | NWS flood map (HGTT2) | NWS flood map (GBHT2) | HAND, **lower confidence** |
| Minor-flood alarm | 2017-08-26 23:29 CDT | 2017-08-26 10:21 CDT | 2017-08-27 05:05 UTC (**fallback threshold**) |
| First road floods | **+75 min** | **+37 min** | +1026 min (unverified) |
| First confirmed zone isolation | +30 min (3 zones, 68 people before the alarm) | −863 min | +6 min |
| HAND vs NWS map, IoU over flooding steps | median 0.64 (0.58–0.84) | median 0.70 (0.27–0.77) | n/a |

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
| Gauge datum | USGS monitoring location |
| Time zone | NWS NWPS; otherwise the USGS monitoring location (standard-time zone and daylight-saving flag); UTC only if neither has one (logged) |
| Stage | USGS 15-min gage height; gaps filled from USGS discharge (including ESTIMATED values, stored as `inferred`) through the event's own rating curve |
| River flooding | NWS flood-map library where published, otherwise HAND (below) |
| Roads | OSM drivable network inside the basin, as of the day before the event (Overpass historical query, logged with fetch timestamps) |
| Zones | OSM street blocks (faces of the road network) with 2020 census population. Blocks with no residents are dropped. Zone ids are deterministic (UUIDv5 of region and normalized block geometry), so reruns update the same zones and cases stay attached |
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
  the river outside that extent have unknown flooding, even near the gauge.
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

### Isolation and bounded reachability

The main network is the largest connected component of the unflooded road
graph. A street block is reachable while at least one road on its boundary is
dry and part of the main network, and isolated when none is. An isolated
block is "stranded" when some boundary road is still dry but cut off, and
"submerged" when all of them are flooded.

Roads whose flooding the river driver cannot determine (they drain to river
outside its coverage) are handled with two bounding runs:

- **Optimistic:** unknown roads are passable.
- **Pessimistic:** unknown roads are impassable while the gauge is at or
  above minor flood stage, and passable below it. The base-flow checks still
  hold.

Each block gets one status:

| Status | Meaning | Written to the zone |
|---|---|---|
| isolated | Isolated even in the optimistic run (confirmed) | countdown to isolation in `isolation_minutes`, as of the minor-flood alarm |
| possibly isolated | Isolated only in the pessimistic run | no countdown; earliest possible isolation time and the reason in `coverage_gaps` |
| reachable | Reachable even in the pessimistic run | no countdown |
| not connected at base flow | Its roads do not reach the main network even with every road dry (network fragments, basin-boundary cuts) | not evaluated; reason in `coverage_gaps` |

Harvey classification:

| Basin | Isolated | Possibly isolated | Reachable | Not connected at base flow |
|---|---|---|---|---|
| White Oak Bayou | 49 zones / 1,156 people | 2,520 / 217,882 | 938 / 101,546 | 15 / 1,537 |
| Greens Bayou | 92 / 5,087 | 949 / 109,999 | 451 / 72,262 | 9 / 238 |
| Hunting Bayou | 11 / 393 | 781 / 32,321 | 225 / 12,344 | 9 / 612 |

The "possibly isolated" band is wide because the flood sources cover little
of each basin. 44.5% of White Oak's roads, 54.5% of Greens' and 37.5% of
Hunting's have unknown flooding, and the pessimistic run blocks them for the
whole 55–72 hours above minor stage. The band narrows only as coverage grows.
The earliest possible isolation time sits at or just after the minor-flood
alarm by construction (that is when the pessimistic run starts blocking
unknown roads). It is not an independent warning signal.

### Cases

Every confirmed-isolated zone opens a `Case` with a
`CaseEngineContribution` from the isolation engine. Cases are opened and
updated every 15 minutes by the case matcher
([case-matcher.md](case-matcher.md)), not by this pipeline. It also appends
later reconnections and mechanism changes.

- `inference_sentence`: plain-language statement of what happened, e.g.
  "Street block with 29 residents was cut off from the main road network at
  2017-08-26 23:00 CDT: all 4 boundary roads stayed dry, but both roads
  leading out of its neighborhood flooded, with USGS 08074500 at 30.29 ft."
- `rule_fragment`: the mechanism the engine found at the isolation timestep,
  i.e. stranded (the flooded exit roads separating the block's dry pocket
  from the network, with road classes) or submerged (all boundary roads
  flooded), plus the river level, stage and river driver.
- `confidence_word = single_source`: one engine, one river source.
- `engine_confidence`: derived from coverage × source agreement × stage
  provenance × library range, with a direction (a reconnection
  contradicts) and time decay applied when read. These are unvalidated
  heuristics; see [confidence.md](confidence.md).
- `opened_at` / `last_contribution_at`: the isolation time.
- `source`: set for replays, e.g.
  `backtest:2017-08-25..2017-09-02:USGS-08074500`, and null for live cases.
  A rerun replaces its own source's cases and never touches others.

Harvey replay: White Oak 49 cases (1,156 people), Greens 92, Hunting 11.
The three White Oak blocks isolated before the alarm (68 people) are
neighbours in one dry pocket whose only two exits (a tertiary road and a
tertiary link) flood together at the 30.7 ft NWS layer.

### Standing checks

Before any isolation output, the pipeline fails loudly
(`BaseFlowFloodingError`) unless, at the first timestep:

- the gauge is below minor flood stage,
- zero road segments are flooded, and
- zero evaluated zones are isolated, in both the optimistic and the
  pessimistic run.

These checks exist because two earlier versions of this engine reported
flooding at base flow that came from modeling errors, not from the event.

## NFIP validation (Proof Layer)

`notebooks/nfip_validation.ipynb`, built and executed by
`notebooks/build_nfip_validation.py`, checks the Harvey replay's isolation
Cases against NFIP claims. Everything is at census block group (BG) level,
since claims are located by BG. The definitions were fixed before the
results were computed:

- **Heavy-claims BG:** the top 20% of a basin's BGs by NFIP claims per 100
  housing units, with at least 5 claims.
- **Spike day:** a BG's peak claims day.
- **Static baseline:** FEMA's floodplain map (NFHL), counting a BG as "at
  risk" if at least 10% of its populated street-block area lies in the
  floodplain.

**Across all 444 BGs (90 heavy) in the three basins:**

| Flag | BGs flagged | Recall of heavy BGs | Flagged BGs that are heavy | Flagged BGs with any claim |
|---|---|---|---|---|
| Isolation Case, any time | 21 | 14.4% | 61.9% | 95.2% |
| Isolation Case before the BG's spike day | 2 | **0%** | 0% | 100% |
| FEMA 100-yr floodplain (static, before the storm) | 159 | **67.8%** | 38.4% | 82.4% |
| FEMA 100+500-yr floodplain (static) | 221 | **82.2%** | 33.5% | 80.1% |
| All BGs (base rate) | 444 | – | 20.3% | 73.0% |

- **The engine does not beat the static floodplain map.** It reaches 14.4% of
  heavy-claims BGs, the map 67.8% (100-year) or 82.2% (100+500-year), and the
  map is available before the storm.
- **Early warning:** no heavy BG got a Case before its spike day began. Ten
  got their first Case during the spike day, which may or may not precede
  that day's damage, since claims carry only a date. Three got it after.
- **Where the engine is more precise:** its flagged BGs are more often heavy
  (61.9% vs 38.4%), but it flags only 21 BGs.
- **Inside the river driver's coverage** (27 BGs, 14 heavy, a very small
  sample), the picture partly flips:
  - The engine reaches 92.9% of heavy BGs, against 64.3% for the 100-year map
    and 92.9% for the 100+500-year map.
  - 65.0% of the BGs it flags are heavy, against 56.2% and 59.1%.
  - By the notebook's fixed rule it beats the 100-year map there but only
    ties the 100+500-year map on recall.
- **Precision can only be stated as a lower bound, and only for flooding,
  not isolation.**
  - 95.2% of engine-flagged BGs recorded some NFIP claim, and 91.4% of
    Cases (139 of 152) had a claim in their BG within a day of opening.
  - Most homes had no flood insurance, so these undercount flooding.
  - A claim records flood damage, not whether a household was cut off, so
    precision for isolation itself cannot be bounded with this data.
  - The base rate is high: 73% of all BGs had some claim.
- **Map vintage:** the NFHL is today's effective map. 7 of the FIRM panels
  touching the basins were made effective in November 2019, after Harvey,
  and 12 of the 159 BGs flagged by the 100-year map touch one. This slightly
  favours the static baseline.

## Rain driver: untestable with current data

A direct-rainfall ponding driver exists in the code (`app.services.rainfall`
and the rain paths of `isolation_engine`):

- AORC hourly rainfall per NHD catchment.
- Drain capacity: the NOAA Atlas 14 2-year 1-hour rainfall.
- Drains keep 50% of that capacity while the gauge is at or above minor flood
  stage. Every run also reports 25% and 100% as a bracket.
- Excess water fills closed depressions at least 0.5 m deep, capped at the
  receiving river level.

Both parameters were chosen on Greens Bayou only, and White Oak and Hunting
are held out. The first version (0% residual drainage, 0.15 m depressions)
isolated every evaluated Greens zone. That was traced to zero drainage:
Harvey's ~0.9 m of rain fills most shallow depressions by itself, so nothing
ever emptied.

**With the fixed parameters the rain driver cannot be tested at all.** The
only usable Sentinel-1 pass (2017-08-29 00:26 UTC) comes about 27 hours after
peak rain. By then the driver has drained all its ponding, in the fit basin
and both held-out basins:

| Aug 29 Sentinel-1 pass | Rain ponding (50%) | River-driver baseline (S1 confirmation) | 25% bracket: ponding / confirmed |
|---|---|---|---|
| Greens (fit) | 0.00 km² | 6.7% | 0.01 km² / not meaningful at that size |
| White Oak (held out) | 0.00 km² | 8.3% | 0.20 km² / 0.1% |
| Hunting (held out) | 0.00 km² | 1.0% | 0.92 km² / 9.4% |

The Aug 30 pass has even less. Every run prints
`VERDICT: does NOT clear (or cannot be checked against) the river-driver baseline`.
The driver is **gated off** (`RAIN_DRIVER_VALIDATED = False`): the engine
refuses to run it and the pipeline produces no rain-driven isolation output.

This is a data limit, not a tuning problem, and no parameter was tuned toward
a passing result. What would make it testable, as the concrete next step:

- **An earlier observation** while ponding is still present, from a
  Sentinel-1 pass (or another SAR or optical sensor) during or within hours
  of peak rain; or
- **Alternative ground truth:** USGS high-water marks, City of Houston 311
  street-flooding reports, or NWS local storm reports, which record where
  and when streets flooded.

AORC rainfall is still ingested and printed as input data.

## Missing stage steps

`app.services.stage` gives each 15-minute step one of three provenances:
- **observed:** gage height within 30 min on both sides;
- **rating:** USGS discharge interpolated between two readings at most
  **3 hours** apart, then converted through the event's rating curve;
- **missing:** neither. The stage is NaN.

**The 3-hour cap is not a physical constant.** It's derived from Harvey: the
widest discharge gap Harvey's rating-filled steps bridge is 150 min (White
Oak; Greens and Hunting 60 min). So Harvey's results are unchanged.

**A missing step is never filled, and nothing downstream treats it as a
level:**
- the flood-map driver gives it no layer (before, NaN selected the *top*
  layer, the largest mapped flood);
- the HAND fallback's depth baseline ignores it;
- the case matcher records **no** evidence at it. Before, a NaN level read as
  "every road dry", which would have reconnected every tracked Case.
  Existing evidence decays instead;
- the pipeline reports how many steps are missing, never names one as the
  peak, and refuses a window that starts with one.

This was built for the Swannanoa (Helene), whose gauge recorded no gage height
for 41 hours.

## Study-area clips

By default a gauge's study area is its whole upstream basin (NLDI). A
registered clip (`app.services.study_area`) can limit it to a documented
boundary:
- **What the clip changes:** everything downstream reads the clipped basin
  (the DEM, HAND, roads and street blocks). The site keeps the full basin,
  and its region name says it's clipped.
- **Other gauges' basins:** a clip can exclude them, so two gauges in one run
  never model the same street block twice.
- **Reproducible:** the clipped polygon is cached with its sources.

Harvey's three gauges aren't clipped. The only clip so far is the French
Broad at Asheville (03451500): Asheville city limits within its basin, minus
the Swannanoa basin, which is 60.0 of 2,446 km². See
[docs/regions/helene.md](../regions/helene.md).

**Rainfall coverage:** the AORC source (the NWM v2.1 retrospective) ends on
2020-12-31. For a later event the pipeline reports "rainfall input: NOT
AVAILABLE" and skips the rain-driver evaluation (`rainfall.RainfallUnavailable`)
rather than crashing. River-driven isolation is unaffected.

**3DEP downloads** retry a transient failure (5xx, connection or timeout) up
to 3 times, waiting 10 s then 30 s, because the service returns intermittent
502s for requests that succeed minutes later.

**Large DEMs are fetched as tiles.** A grid wider or taller than 2,000
cells is requested as tiles of at most 2,000 × 2,000 and stitched
(`terrain._download_tiled`). The limit comes from observation, not a
published 3DEP limit: the Swannanoa's single 2,861 × 2,691 export returned
HTTP 500 six times in a row, while the French Broad clip's 2,401 × 1,690
succeeded. Every tile is cut on the full grid's own cell boundaries, so 3DEP
samples the same cell centres a single export would. Checked live
(2026-10-05): a 610 × 430 area fetched as 6 uneven tiles matched the single
export on all 262,300 cells, with 0 differences. Harvey's DEMs were
downloaded earlier in one request each and are cached, so they're unchanged.

## Known limitations and assumptions

- **Tunnels are not exempt from flooding.** Spec §2 exempted bridges and
  tunnels from terrain-based flood removal. Only bridges are exempt here: they
  are elevated above the flood surface. Tunnels and underpasses are below grade
  and flood first, a known Houston hazard. This is a deliberate, corrected
  deviation from the spec.
- **Layer-convention sensitivity.** Lead times move by about 15 minutes
  between NWS's round-up convention and round-down (tables above).
- **Coverage is small.** The NWS libraries cover 2.53 km² (White Oak) and
  6.76 km² (Greens) of their basins, which is why most residents fall in the
  "possibly isolated" band.
- **Coarse claims timing.** NFIP claims only carry a date of loss, so lead
  times against claims are ranges over a whole day.
- **Stage gaps.** They are filled through a rating curve that ignores
  hysteresis (White Oak Bayou: 426 of 865 steps, because the gauge stopped
  recording stage at the Harvey peak).
- **Fallback thresholds can mix datums.** Annual peak series can span
  gauge-datum changes, which the percentile fallback does not correct for.
- **Undirected road graph.** One-way rules are ignored (rescue vehicles).
- **Sentinel-1 misses urban flooding.** Water among buildings raises radar
  backscatter, so confirmation rates are low even for the validated river
  driver (1–8%). The river driver's own rate is the baseline other drivers
  must match.
