# Second region: Hurricane Helene, Asheville, NC (September 2024)

Status: **data pulled; study area set; no results yet.** The French Broad gauge
has passed its dry run. The Swannanoa gauge's results are **gated**: nothing
from it is run, looked at or reported until the gap-fill fix (a step with no
data stays "missing", not interpolated) is merged and verified.

**Every number below carries the date it was checked.** USGS figures for this
event were provisional and have been revised since (see "Revised provisional
figures").

## The two gauges (checked 2026-10-04)

| | French Broad River at Asheville | Swannanoa River at Biltmore |
|---|---|---|
| USGS / NWS | 03451500 / AVLN7 | 03451000 / BLTN7 |
| Upstream basin | 2,446 km² (945 sq mi) | 339 km² (130 sq mi) |
| NWS flood stages | action 6.5, minor 9.5, moderate 13, major 18 ft | action 9, minor 10, moderate 14.5, major 16.5 ft |
| NWS flood-map library | **none**, so the river driver uses **HAND** (lower confidence, as at Hunting Bayou) | **yes** (`FIM_bltn7`) |
| Gage height, 24 Sep – 3 Oct 2024 | **865 of 865** 15-minute readings; no gap over an hour; peak **24.82 ft** at 2024-09-27 21:38 UTC (113,000 cfs) | gaps across the peak; the peak, **27.33 ft** at 19:00 UTC on 27 Sep, is a **single isolated reading**; then **no gage height for 41 hours** (02:30 UTC on 28 Sep to 19:30 UTC on 29 Sep) |
| Discharge in that gap | n/a | only sparse 4-hourly values, marked **ESTIMATED** |
| What it tests | HAND on a clean record | a flood-map library on a gauge whose data feed fails |

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
10 m cells for the HAND build) is **future work, not done.**

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
  Stage-to-discharge relationships at the peak are extrapolations. The
  Swannanoa's flood-map library may not reach its 27.33 ft peak, and above
  its highest mapped stage the engine applies its lower-confidence
  above-library factor.
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
