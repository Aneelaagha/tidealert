# Submission fields (draft)

Each field describes only what is built and merged as of 2026-10-06, and ends with one "Next" line for the rest. Each is
under 1,200 characters (checked by `tests/test_submission_docs.py`). Wording is a draft for the owner to edit.

## Disaster Scenario

TideAlert answers one question during a river flood: which neighbourhoods have lost every road out, and who should be looked at first. It is built and tested on Hurricane Harvey (Houston, 25 Aug to 2 Sep 2017) in three bayou basins, replayed from recorded USGS gauge data. From a gauge's stage it floods the road network and finds street blocks with no dry way out. At the peak (27 Aug, 20:00 UTC) all 152 flagged blocks are cut off at once. The first road floods 37 to 75 minutes before the NWS minor-flood alarm at the two gauges with an NWS flood map. It is a replay, not a live system, and no real responders appear in it. A second event, Hurricane Helene (Asheville, 2024), is run too, and found no confirmed isolations.

Next: connect live gauges so the same view runs on a flood as it happens.

## Timeliness & Reliability

The page reads the run as of any time on a slider and shows, per source, whether its newest reading is fresh or stale by a stored rule. Where a gauge's data fails, the gap stays missing: nothing is filled beyond a 3-hour cap taken from Harvey's widest bridged gap, and the Helene Swannanoa gauge's 41 hours of missing data are shown as missing. If the server is lost the page keeps the last view, read-only, and reopens from a saved copy after a reload, labelled with when it was saved. Current USGS readings are shown separately, labelled as not a live run. A Last call countdown gives the engine's cut-off time minus a lead time the operator sets, per zone, in hindsight. Validation is on the page: the engine does not beat FEMA's static floodplain map against insurance claims (14.4% vs 67.8% of heavy-claims areas). Confidence words are unvalidated heuristics.

Next: validate against observed isolation, which no dataset records, and speed up the zones endpoint: on one worker the full dashboard fails our load target.

## Comprehensiveness & Data

Inputs are public: USGS gage height and discharge, NWS flood stages and flood-map libraries, USGS 3DEP elevation, OpenStreetMap roads as of the day before the event, Census 2020 blocks and population, OpenFEMA NFIP claims, and Sentinel-1 for checks. Each block gets a status (cut off, may be cut off, reachable, not assessed), with bounds for roads whose flooding is unknown. On top: Cases and tasks with a stated rule, supply access (can a dry route reach a zone), depot access from nine real fire stations, operator-entered needs and donor offers, and an after-action report built from stored rows. Two scenario engines (silence, listening) run on synthetic households only. No data about real households is used.

Next: rainfall from NOAA AORC for 2024 and a landslide model, which Helene shows are missing.

## Integration & Responsible Data

A FastAPI and PostGIS service with a React page. Every route is scanned for personal fields, and the scan fails on a new write route until it is reviewed. No household phone, age, disability or location is returned. Real-household results are never sent to an external model. The copilot's wording is checked: every number and status it states is filled in by the server from stored values. Synthetic and typed-in material is labelled: the mixed run (real flood, synthetic responders), operator-entered needs, and donor offers, which take no money and keep no contact details. Known gaps are listed in the app: no login, no consent collection, no retention policy, a copy of the last view kept on the device, and free-text notes the scan cannot read.

Next: authentication, consent and a retention policy before any real household data.

## Usability

Start here opens Harvey at its peak, frames the map, and selects the first zone to look at. A one-line headline says how many flagged zones are cut off and how many responders are assigned, and names the event. A ranked list of zones that need attention states its rule. Colour layers (risk, supply access, depot access) have an on-map legend. The operator bar says in plain words why a replay can't be changed and switches to the mixed scenario in one click. The report downloads as Markdown, with the run's mode first. Caveats are one click away on every page. It has been driven in a desktop browser only; phone layout and accessibility have not been tested.

Next: usability testing with emergency managers, a phone layout and an accessibility review.
