# Supply access

Whether a supply run can reach each zone from the main road network, as of the slider time. **Route feasibility
only.** It adds no measurement: it is the isolation engine's stored output, read for every zone of a run.

- `backend/app/services/supply_access.py`, `GET /map/supply-access?run_id=&at=` (`backend/app/routes/map.py`).
- Each zone's state is the one responder safety already reports for a task's zone
  (`app.services.safety.zone_access`, see `task-lifecycle.md`), computed for all of the run's zones, not only those
  with a task. A test checks the two agree on every task's zone.
- Kept apart from `/map/zones` (about 6 MB for Harvey) so that response doesn't grow. Harvey: about 0.2 s, 0.8 MB.
- The page reads it only when something shows it: the **Supply access** map colour, or a selected zone's panel.

## States

| State | Meaning |
|---|---|
| `isolated` (cut off) | Every route to the main road network is flooded, even with roads of unknown flooding taken as passable. |
| `possibly_isolated` (may be cut off) | Cut off only if roads of unknown flooding are flooded. |
| `reconnected` | Was cut off; the engine's latest evidence is a reconnection. The **optimistic** bound, so it is not called reachable. |
| `reachable` | A dry route exists even if every road of unknown flooding is flooded. |
| `not_evaluated` (not assessed) | A permanent coverage gap, or the engine never ran on the region (every synthetic scenario). **Never** read as safe or reachable. |

The response counts zones and recorded population per state, gives each zone its state, the start of the isolation
and its mechanism (stranded or submerged), and the engine's own reason (deduplicated into `reasons`). Population is
the zone's recorded count; a zone with none recorded counts as 0 people, not as an estimate.

## What it does not show (also returned as `does_not_show` and shown on the page)

- **Where a supply run would start.** No depot or staging data exists, so there is no origin and no route.
- Distance or time, vehicle suitability, or which roads to take. No route-by-route flood state is stored, so no
  route geometry is returned.
- Whether a dry road is passable (debris, damage, closures). Road capacity is not modelled.
- That "reachable" is safe: it is a statement about flooding the engine could evaluate.

## Harvey, as measured by the engine (2017-08-27 18:30 UTC, the isolation peak)

133 zones (4,463 people) cut off, 4,250 (360,202) may be cut off, 1,633 (188,325) reachable, 33 (2,387) not assessed.
Before the flood (2017-08-26 12:00 UTC) none is cut off. "May be cut off" stays active for the rest of the window,
because the engine stores only when it first became possible, not when it ended.

Helene's run has no zones in view (0 Cases, so no zone is selected for it); the page says so. The synthetic
scenarios read every zone as not assessed.

## Not built, on purpose

- **A route from a staging point.** It would need an operator-entered origin (invented on replayed data, not
  measured) and a per-timestep recompute of flooded roads, which touches the isolation engine and so needs its own
  Harvey review. Documented future work.
- **Supply needs or a donations board.** Deferred past Week 7.
- **The copilot** does not answer supply questions; it is unchanged.
