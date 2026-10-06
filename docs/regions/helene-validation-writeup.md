# Helene validation write-up (draft for the owner's review)

What the Hurricane Helene run (Asheville, NC, 2024-09-25 to 2024-10-01) can and cannot say about the engine. Every number
here is read from the stored run files and is on the Validation panel's Helene tab, pinned by
`tests/test_validation_helene.py` to `docs/regions/helene.md`. Read it as a negative-result report.

## What was tested

The same isolation pipeline as Harvey, on a second region and a second event, at two gauges: the French Broad at
Asheville (clipped to the city limits, 60 km2, 2.5% of its basin) and the Swannanoa at Biltmore (its full 339 km2 basin).
Neither gauge has a usable NWS flood map, so both ran on HAND, the engine's lower-confidence river driver.

## What happened

- **No zone was confirmed isolated at either gauge, so no Case opened.** Zones: Swannanoa 0 of 668 confirmed (512 possibly
  isolated, 148 reachable, 8 not connected at base flow); French Broad 0 of 555 (170, 243, 142).
- **HAND barely engaged:** 48 road segments ever flooded at the Swannanoa and 1 at the French Broad, against about 1,270
  segments whose flooding the engine cannot assess at each.
- **Where the data failed, the engine said so:** the Swannanoa gauge recorded no gage height for 41 hours across the crest.
  150 of its 577 steps are missing and are left missing (the gap-fill cap is 3 hours, from Harvey's widest bridged gap of
  150 minutes), not inferred.
- **Rainfall was skipped,** not invented: the pipeline's rainfall source ends in 2020, so the rainfall summary and the
  rain-driver evaluation did not run.
- **Ground truth is NFIP claim counts only:** 294 claims (233 on 27 Sep) and 73 (59 on 27 Sep) in the two gauges' block
  groups. Counts, not rates; located by block group and dated by day.

## What it shows, and what it does not

It shows the pipeline runs end to end on a second event and fails visibly rather than guessing. It does **not** show
that the engine detects isolation in Helene, and it does **not** show that nothing was isolated. The zero is
consistent with the engine's known blind spots (below), but this run cannot separate those causes from a real absence of
river-driven isolation, because there is no ground truth at the peak.

## Limitations (these are on the panel)

- **Landslides, debris flows and washed-out roads and bridges are not modelled.** Much of western North Carolina's
  isolation came from them. Expect the engine to miss real isolations.
- **HAND in steep terrain:** it assumes constant depth along the gauged reach, which fits narrow mountain valleys worse than
  Houston's flat bayous.
- **No peak-time ground truth:** no USGS high-water marks exist for either river; Sentinel-1 passes were six days before
  and after the crest; the three Buncombe County flood reports came before it; NFIP claims are the only ground truth and
  are about 100 times sparser than Harvey's.
- Neither gauge has a usable NWS flood map; USGS reported many gauges damaged or peaking above their ratings; the French
  Broad covers 2.5% of its basin; HAND's confidence is borrowed from Harvey's libraries.

## Not done (documented future work)

- A **full-basin French Broad run** (2,446 km2). Tiled 3DEP downloads now remove the request-size obstacle that blocked it,
  but it has not been run; see "Full-basin French Broad" in `helene.md` for its status.
- NOAA's AORC v1.1 rainfall for 2024.
- Landslide and debris-flow modelling.
