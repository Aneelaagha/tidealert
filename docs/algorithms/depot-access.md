# Depot access (supply routing, feasibility only)

Whether a supply run starting at a depot can reach a zone by a **dry road route**, at each time step of the Harvey replay,
using the isolation engine's own machinery. **No optimisation, no route, no distance, time, vehicle or capacity.**

- `backend/app/services/depot_reach.py`: the engine's flooded-road test (`flooded_edges`), its optimistic and
  pessimistic treatment of roads of unknown flooding, and its connected-components test, asked a different question.
  The engine asks "can this zone reach the main road network?"; here the "main network" is the part of the road network the
  depot's road belongs to at that step. `app/services/isolation_engine.py` is **not changed**.
- `scripts/depot_access.py` rebuilds the engine's inputs exactly as `run_isolation_pipeline.py` does (cached DEM, terrain,
  roads and the stored gauge record), **writes no database rows**, and stores one file per gauge,
  `backend/app/data/usgs-<site>/depot_access.npz`, at the page's 30-minute ticks.
- `GET /map/depots` and `GET /map/depot-access?run_id&depot_id&at` (`app/services/depots.py`) read those files. The page's
  **Depot access** layer colours a depot's basin and a picker chooses the depot. Only the Harvey runs have it.

## The depots

Real fire stations from OpenStreetMap (`amenity=fire_station`) inside each basin's modelled road network, snapped to the
nearest road within 150 m, three per basin spread west to east (nine in all), with their OSM ids and the fetch time
(2026-10-06), recorded in the tracked file `backend/app/depot_candidates.json`, from which `scripts/depot_access.py` regenerates the results without asking Overpass again (`--refetch` asks again). The result files are generated data under `backend/app/data/`, which is gitignored like the backtest files. A station that snaps onto a road fragment cut off from the network even when dry is dropped. **Nothing says any
of them served as a depot in Harvey:** they are example origins to ask the question from.

## States (per zone and step)

| State | Meaning |
|---|---|
| reachable | a dry route exists even if every road of unknown flooding is flooded (the pessimistic bound) |
| only if unknown roads are passable | a dry route exists in the optimistic run only |
| not reachable | no dry route even with unknown roads passable (the depot's roads and the zone's are cut apart, or the depot's own road is flooded) |
| not assessed | the engine could not evaluate the zone |
| other basin's network | the zone is in a different gauge's road network: not assessed from this depot |

## It reduces to the engine (checked)

`depot_access.py` stops with an error unless, at every step where the depot is in the main network, "not reachable" is
**exactly** the set of zones the engine's optimistic run calls isolated: 1,299 depot-steps for White Oak, 1,299 for Greens
and 1,262 for Hunting Bayou, 0 mismatches. `tests/test_depots.py` re-checks it against the stored evidence behind supply
access: at the 20:00 UTC peak, "not reachable" from a depot in the main network is 49 zones (White Oak), 92 (Greens) and 11
(Hunting), the engine's confirmed-isolated counts.

## Limits

- A depot that is itself cut off can reach the zones on its own island and little else. One Hunting Bayou station is in that
  position at the peak; the layer shows it, with "this depot's own road is flooded" where its road is under water.
- "Reachable" is flooding only: debris, damage, closures and road capacity are not modelled, and a dry route is not a
  passable one. The depot is snapped to the nearest road segment, not an intersection or a gate.
- Three depots per basin; a depot anywhere else is not computed (the page cannot take a clicked point).
- The flooding behind it is the engine's: HAND at Hunting Bayou is lower confidence, and roads of unknown flooding are
  bounded, not resolved.
