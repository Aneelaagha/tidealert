# Second region: Hurricane Helene, Asheville, NC (September 2024)

Status: **both gauges run (2026-10-05); results below, not yet interpreted for
the write-up.** The Swannanoa's gate (the gap-fill fix) is merged and verified.

**Every number below carries the date it was checked.** USGS figures for this
event were provisional and have been revised since (see "Revised provisional
figures").

## The two gauges (checked 2026-10-04)

| | French Broad River at Asheville | Swannanoa River at Biltmore |
|---|---|---|
| USGS / NWS | 03451500 / AVLN7 | 03451000 / BLTN7 |
| Upstream basin | 2,446 km² (945 sq mi) | 339 km² (130 sq mi) |
| NWS flood stages | action 6.5, minor 9.5, moderate 13, major 18 ft | action 9, minor 10, moderate 14.5, major 16.5 ft |
| NWS flood-map library | **none**, so the river driver uses **HAND** (lower confidence, as at Hunting Bayou) | **published (`FIM_bltn7`) but refused:** it doesn't resolve stage (see below), so the river driver uses **HAND** (lower confidence) |
| Gage height, 24 Sep – 3 Oct 2024 | **865 of 865** 15-minute readings; no gap over an hour; peak **24.82 ft** at 2024-09-27 21:38 UTC (113,000 cfs) | gaps across the peak; the peak, **27.33 ft** at 19:00 UTC on 27 Sep, is a **single isolated reading**; then **no gage height for 41 hours** (02:30 UTC on 28 Sep to 19:30 UTC on 29 Sep) |
| Discharge in that gap | n/a | only sparse 4-hourly values, marked **ESTIMATED** |
| What it tests | HAND on a clean record | HAND on a gauge whose data feed fails (missing steps stay missing) |

**The Swannanoa basin drains into the French Broad above the Asheville
gauge.** The French Broad's study area excludes it, so the two regions' street
blocks are disjoint.

## Study area: the French Broad is clipped

| | km² |
|---|---|
| French Broad upstream basin (NLDI) | 2,446.2 |
| Asheville city limits (Census 2020 incorporated place 3702140) | 119 |
| City limits inside the French Broad basin | 96 |
| **Modelled: city limits ∩ basin, minus the Swannanoa basin** | **60.0 (2.5% of the basin)** |

The gauge lies inside the modelled area. **Why:**
- The full basin can't be exported from USGS 3DEP in one request. It failed
  with HTTP 500, even after the code had coarsened it to about 19 m.
- This region is being tested for HAND behaviour near the gauged reach, not
  for full-basin coverage.

**Effect:** only street blocks inside the modelled area exist for this gauge,
and nothing outside it is assessed. The clip is `app.services.study_area`; its
polygon is cached in `backend/app/data/usgs-03451500/study_area.json`.

**Tiled 3DEP downloads now exist** (built for the Swannanoa; see the isolation
engine doc), so the 3DEP request limit is no longer the obstacle. **The French
Broad stays clipped, as decided:** this region tests HAND near the gauged
reach. A full-basin French Broad run (about 2,446 km², tens of millions of
10 m cells for the HAND build) was **opt-in only** when this was written; see
"Full-basin French Broad (opt-in)" below for what has been measured since.

**Dry run of the data stages, clipped (2026-10-05):**

| Stage | Result |
|---|---|
| DEM | 10 m, 2,401 × 1,690 cells, 11 s |
| Terrain/HAND build | 7.6 s; 1,157 gauged-mainstem cells |
| OSM roads (as of 24 Sep 2024) | 3,888 segments, 76 bridges, 13 s |
| Street blocks | 555, with 31,901 residents, 4 s |
| Total | 45 s; peak memory about 0.6 GB |

**3DEP reliability:**
- The service returned intermittent HTTP 502s even for this small request,
  which succeeded minutes later. `download_dem` now retries a transient
  failure (5xx, connection or timeout) up to 3 times, waiting 10 s then 30 s.
- The Swannanoa's full basin (339 km², 2,862 × 2,692 cells at 10 m) failed as
  a single export: HTTP 500 six times in a row. It succeeded as 4 tiles in
  61 s (2026-10-05).

## Results (run 2026-10-05; window 2024-09-25 04:00 to 2024-10-01 04:00 UTC)
Both gauges run on **HAND (lower confidence)**. Neither has a usable NWS flood
map (see below).

| | Swannanoa 03451000 | French Broad 03451500 (clipped) |
|---|---|---|
| Stage steps (15 min) | 577: 399 measured, 28 from the rating curve, **150 missing** (nothing inferred) | 577: all measured |
| Peak | 27.33 ft at 19:00 UTC on 27 Sep (a single reading) | 24.67 ft at 21:30 UTC on 27 Sep on the 15-min grid (24.82 ft at 21:38 off-grid) |
| Road segments | 5,436 | 3,885 |
| Ever flooded (known) | **48** (0.9%) | **1** |
| Flooding unknown (outside HAND's reach coverage) | 1,273 (23.4%) | 1,273 (32.8%), the same count by coincidence (checked) |
| First road floods | 06:45 UTC on 26 Sep, 234 min after the minor-flood alarm | 17:30 UTC on 27 Sep, 1,756 min after the alarm |
| **Confirmed isolated** | **0 zones** | **0 zones** |
| Possibly isolated (only if unknown roads flood) | 512 zones, 29,440 people | 170 zones, 8,160 people |
| Reachable | 148 zones, 10,075 people | 243 zones, 15,112 people |
| Not connected at base flow | 8 zones, 138 people | 142 zones, 8,629 people |
| **Cases opened** | **0** | **0** |
| NFIP claims in the zones' block groups (date of loss, EDT) | 294 in total; 233 on 27 Sep | 73 in total; 59 on 27 Sep |

**What this does and doesn't show:**
- **No Case opened anywhere,** because no zone is confirmed isolated, and
  Cases open only on confirmed isolation. The engine's "possibly isolated"
  bound covers most residents (74% at the Swannanoa, 26% at the French
  Broad), but it rests on roads whose flooding the engine can't assess.
- **HAND barely engages near Asheville:** 48 and 1 segments ever flood.
  This is consistent with the limitations below (steep valleys; HAND's
  constant-depth assumption; landslides and washouts not modelled), but this
  run can't separate those causes.
- **NFIP claims are counts, not rates.** They're located by block group and
  dated by day, not time, so they can't confirm or refute any single zone.
- **The French Broad's 142 zones not connected at base flow** come from the
  city-limits clip cutting the road network. They aren't evaluated, and the
  report gives the reason.
- **HAND's confidence here is borrowed from Harvey's Houston libraries**
  (White Oak and Greens Bayou): no Helene gauge has a usable library to
  measure it locally.

## The Swannanoa's flood-map library is refused (checked 2026-10-05)
NWS publishes a flood-map library for BLTN7, but the engine doesn't use it:
- **Its layers are water-surface elevations,** 1,980 to 1,996 ft NAVD88. The
  gauge datum is 1,976.37 ft (USGS); NWS's own zero datum is 1,976.29 ft.
  So the layers span gage heights of **3.6 to 19.6 ft**.
- **Its extent barely changes across that range:** 1.054 km² at the lowest
  layer, 1.085 km² at the highest.
- **Even the lowest layer maps 1.05 km² under at least 1 ft of water,** at a
  gage height of 3.6 ft. That day's base flow was 1.9 ft; action stage is
  9 ft. Identify queries at 60 points returned positive depths at every
  layer, so this is the library's own data, not how the engine reads it.
- **Used as published, it would flood 84 road segments on the evening of 25
  Sep,** with the river at 3.8 ft, more than a day before it reached action
  stage.
- **Why it behaves this way is unknown.** One possibility is a flat water
  surface that spreads onto lower ground downstream toward the French Broad
  confluence; that's unconfirmed. NWS's downloadable depth grids return 404.

**So the Swannanoa uses HAND,** like the French Broad: lower confidence,
assuming constant depth along the gauge's reach, which fits steep terrain
worse (see the limitations). Harvey's two libraries pass the same check
easily.

## Ground truth (checked 2026-10-04 and 2026-10-05)

| Source | What exists | Usable? |
|---|---|---|
| **NFIP claims** (OpenFEMA) | 498 claims in Buncombe County with loss dates 24 Sep – 5 Oct 2024, against 48,702 in Harris County for Harvey. Claims carry a date, not a time, and are located by block group. | **Yes, the only ground truth.** Counts reported as counts; no rates where the numbers are small. |
| USGS high-water marks (STN, event 346 "2024 Helene") | 321 marks in total, **none** on the French Broad or the Swannanoa. The nearest is about 65 km away (Middle Saluda River). USGS says field crews measured marks after Helene, but none for these rivers is published in STN. | No. |
| Sentinel-1 SAR | Only Sentinel-1A (12-day repeat): passes on **21 Sep** (6 days before the peak) and **3 Oct** (6 days after). Steep valleys had drained by then. | No. |
| Sentinel-2 optical | 2 Oct (5 days after the peak). NASA describes "brown slicks of mud and debris" around the town of Swannanoa as the water receded. | No: late, and at best a lower bound. |
| NWS local storm reports (Iowa Environmental Mesonet archive, WFO GSP) | 84 reports; **3 flood reports in Buncombe County, all before the peak** (25 Sep about 23:15 UTC; 27 Sep 01:37 UTC). None during the peak. | No: nothing at the crest. |
| NC FIMAN | No published inundation product found for these rivers or Helene. | Not found. |

## Revised provisional figures
USGS's release of **2024-10-04** gave the French Broad at Asheville a
*provisional* record of **24.67 ft**, and said values "will be verified or
revised". On 2026-10-04 the USGS record gives **24.82 ft**. NASA (5 Oct 2024)
and press coverage gave the Swannanoa crest as **26.1 ft**; the USGS record now
gives **27.33 ft**. Any figure cited for this event therefore needs the date it
was read.

## Limitations specific to this region (for the submission)
These are written in Helene's own terms rather than folded into the general
gaps, because the model fails differently here than in Houston.

- **The engine models river water over roads. Helene cut roads in ways it
  doesn't model.** Much of western North Carolina's isolation came from
  **landslides, debris flows and washed-out roads and bridges**, and the
  engine models none of these. Expect it to **miss real isolations**,
  especially away from the gauged reach.
- **HAND fits steep terrain worse.** HAND assumes constant water depth along
  the gauged reach and fills land below the water surface. That works better
  in flat Houston bayous than in narrow mountain valleys, where the water
  surface slopes steeply and debris dams change it.
- **The instruments themselves were out of range.** USGS reported that about
  60 sites serviced by its Asheville field office had peak gage heights
  **exceeding their current ratings**, and that many streamgages were
  "destroyed by floodwaters or damaged by wind and debris" (USGS, 2024-10-04).
  Stage-to-discharge relationships at the peak are extrapolations.
- **Neither gauge has a usable NWS flood map.** The French Broad has none,
  and the Swannanoa's is refused (above). Both run on HAND, the engine's
  lower-confidence driver, in the terrain where HAND fits worst. The
  Swannanoa's library topped out at a gage height of 19.6 ft anyway, well
  below its 27.33 ft peak.
- **The Swannanoa's data feed failed.** For 41 hours there is no gage height,
  and only sparse estimated discharge (4-hourly, beyond the 3-hour rating
  cap). With the gap-fill fix, those steps are **missing**: no river level,
  no new isolation or reconnection evidence. The system says it's blind
  there rather than inferring. Its freshness banner is a separate change
  (counting only measured readings), under its own review because it also
  changes Harvey's banner.
- **Ground truth is thin:** NFIP only, about 100 times sparser than Harvey's.
- **The French Broad covers 2.5% of its basin** (the clip above).
- **There's no rainfall input for this event.** The pipeline's rainfall source,
  the NWM v2.1 retrospective's AORC forcing
  (`noaa-nwm-retrospective-2-1-zarr-pds/precip.zarr`), ends on 2020-12-31
  (checked 2026-10-05). The pipeline now says so
  (`rainfall.RainfallUnavailable`) and skips the rainfall summary and the
  rain-driver evaluation. The river-driven isolation output doesn't depend
  on either, and the rain driver is gated off anyway. **Future work, not
  done:** NOAA's AORC v1.1 archive (`noaa-nws-aorc-v1-1-1km`, per-year Zarr)
  covers 2024 and 2025. Reading it would need a second reader for its
  layout, for an input that feeds a driver this region can't validate (no
  Sentinel-1 pass near the peak).

## Sources
- USGS, *USGS collecting flood data and repairing streamgages damaged by
  hurricane* (2024-10-04):
  <https://www.usgs.gov/news/national-news-release/usgs-collecting-flood-data-and-repairing-streamgages-damaged-hurricane>
- NASA Earth Observatory, *Flash Floods Swamp North Carolina* (2024-10-05):
  <https://science.nasa.gov/earth/earth-observatory/flash-floods-swamp-north-carolina-153416/>
- USGS Water Data (continuous gage height and discharge), via
  `app.services.ingest`; USGS STN (`stn.wim.usgs.gov/STNServices/Events/346/HWMs.json`);
  NWS NWPS (AVLN7, BLTN7); Microsoft Planetary Computer STAC (`sentinel-1-rtc`,
  `sentinel-1-grd`); Iowa Environmental Mesonet LSR archive; Census TIGERweb
  2020 (incorporated places); OpenFEMA NFIP claims (v2).

## Full-basin French Broad (opt-in; data stages measured 2026-10-06)

`TIDEALERT_STUDY_AREA_FULL=1` models the whole upstream basin (minus the Swannanoa basin, so the two regions stay disjoint)
instead of the city-limits clip. It has its own cache directory (`usgs-03451500-full`) and its own region label
(`USGS-03451500 basin, full basin`), so **nothing of the clipped run is overwritten or shared**: the default is unchanged
and `tests/test_study_area.py` checks both. `scripts/helene_dry_run.py` and `scripts/run_isolation_pipeline.py` honour it.

**Dry run of the data stages, full basin (2026-10-06):**

| Stage | Result |
|---|---|
| Modelled area | 2,107 km² of the 2,446 km² basin (the rest is the Swannanoa basin, modelled separately) |
| DEM (3DEP, tiled) | **16.1 m**, not 10 m: the basin is wider than the 10 m pixel cap (`DEM_MAX_PIXELS`), so the code coarsens it; 3,911 × 4,000 cells, 111 s |
| Terrain/HAND build | 27.5 s; 9,471 gauged-mainstem cells |
| OSM roads (as of 24 Sep 2024) | 26,769 segments, 402 bridges, 43 s |
| Street blocks | 2,577, with 224,069 residents, 26 s |
| Total / peak memory | about 3.5 min; peak 2.9 GB |

**What this does not yet show:** the dry run stops before the river driver, the isolation engine and the backtest, so it has
**no flood, isolation or lead-time result**. A full run needs those stages; see the PR for its status. The coarser DEM (16 m
against 10 m) makes HAND coarser still in narrow valleys, and everything in "Limitations specific to this region" above
still applies (HAND in steep terrain, landslides and debris flows not modelled, no peak-time ground truth, no rainfall input).
