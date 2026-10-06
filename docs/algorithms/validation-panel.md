# Validation panel

How the Hurricane Harvey backtest did, inside the product (**Validation** button, `GET /validation/harvey`).

- `backend/app/services/validation.py` **reads** every number at request time from where it is stored: the three
  `backend/app/data/usgs-*/backtest.json` files and the executed `notebooks/nfip_validation.ipynb` (its printed tables,
  with the time each cell ran). Nothing is typed into the service.
- Each row shows its **run** (`backtest:2017-08-25..2017-09-02`), the **event window**, the **file and field** it was read
  from and, for the NFIP results, when the notebook ran.
- `tests/test_validation.py` pins every displayed number to its source, the way the data-practices panel is pinned:
  it reads the same place independently and compares, then checks the numbers against the tables written in
  `docs/algorithms/isolation-engine.md`. A changed result fails the test until the docs and the panel agree.

## What it shows

- **Lead time before the NWS minor-flood alarm:** the first road floods 75 min (White Oak) and 37 min (Greens) before
  the alarm, both gauges with an NWS flood map. Hunting Bayou reads +1,026 min, marked unverified (HAND flood source at
  lower confidence, and its alarm is a percentile fallback, not an NWS threshold).
- **Zones by status** per basin, **HAND vs the NWS map** overlap, and the **NFIP check**.
- **The weak result is on the headline next to the strong one:** against NFIP claims the engine's Cases reach 14.4% of
  the 90 heaviest-claims block groups; FEMA's static 100-year floodplain map reaches 67.8% (100+500-year: 82.2%) and
  exists before the storm. The engine does not beat the static map.

## What it does not show

No observed isolation exists to test against, so none of this proves the engine finds blocks that were actually cut
off. It is one event in three basins. NFIP claims record damage, not isolation, and undercount flooding. Inside the
river driver's coverage the NFIP sample is 27 block groups. The rain driver and landslides are not modelled. These
limits are listed on the panel.
