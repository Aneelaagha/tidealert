# Current gauge readings

A read-only view of the latest USGS readings for the gauges this project uses (**Gauges** button, `GET /gauges/current`).

**It is not LIVE mode.** Nothing here feeds the engines, nothing is stored, and no Case, task or zone depends on it. The
replays on the page are recorded data, not these readings. The panel says so.

- `backend/app/services/gauge_readings.py` asks USGS's OGC API (`api.waterdata.usgs.gov`, the service the ingest uses)
  for the newest gage height (00065) and discharge (00060) at the five gauges: White Oak, Greens and Hunting Bayou
  (Houston) and the French Broad and Swannanoa (Asheville). At most one fetch a minute.
- Each value shows when USGS observed it, its approval status (provisional), and the time it was fetched.
- **Freshness** uses the stale-after rule stored for each source in `data_sources` (15-minute cadence, stale after one
  hour). A gauge with no stored rule reads "unknown". At the time of writing, two gauges' newest readings were just
  over an hour old and read stale: that is USGS's own publishing lag, reported as it is.
- **If USGS can't be reached** (or returns nothing) the endpoint answers `available: false` with the reason, and the
  panel shows "Readings unavailable" and no values. A gauge that fails alone reads "unavailable" and never borrows
  another reading or an older one. If the TideAlert server itself can't be reached, the panel says that instead (and
  the connection banner applies).
- The legacy `waterservices.usgs.gov/nwis/iv` service returned HTTP 503 when this was built, so the newer OGC API is used.

Tests (`tests/test_gauge_readings.py`) inject the fetch, so they don't need the network: fresh vs stale at the stored
limit, the unavailable and empty-answer cases, a single failing gauge, and the route when the network is down. One
opt-in test asks USGS for real and skips if it can't be reached.
