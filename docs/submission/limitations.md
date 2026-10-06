# What TideAlert does not do (one page)

Written for the submission. Every line is a limit of what is built, stated plainly. Sources: `docs/algorithms/`,
`docs/regions/helene.md`, and the Validation and Data & ethics panels in the app.

## It is a replay, not a live system
- The page replays Hurricane Harvey (2017) from recorded USGS data. No live gauges feed the engines. The "Gauges" view shows
  current USGS readings and says it is **not** a live run.
- **No real responders appear anywhere.** The mixed scenario puts synthetic responders over Harvey's real flood and says so in
  its badge, its banner and its report. Needs and donor offers in it are typed in by whoever uses it.

## The results are narrower than the interface
- **One event, three basins.** Timing is tested against the NWS minor-flood alarm, and location against NFIP insurance claims. Nobody
  recorded when a block was actually cut off, so there is **no observed-isolation ground truth**.
- **The engine does not beat a static map** at finding the heaviest-claims areas: 14.4% against 67.8% for FEMA's 100-year floodplain
  (82.2% for 100+500-year). Its strength is timing and precision on the few areas it flags, not coverage.
- **Confidence words are unvalidated heuristics**, not calibrated against outcomes.
- **Helene found nothing.** No zone was confirmed isolated at either Asheville gauge and no Case opened. That does not show
  nothing was isolated: landslides, debris flows and washed-out roads are not modelled, HAND fits steep terrain poorly, and there is
  no peak-time ground truth. The French Broad run covers 2.5% of its basin; a full-basin run is not done.
- **Hunting Bayou is lower confidence** (HAND, with a fallback flood alarm): its lead time is unverified.

## Feasibility, not routing
- Supply access and depot access say whether a **dry route exists**. They find no route and give no distance, time, vehicle or capacity.
  Debris, damage and closures are not modelled. The nine depots are real fire stations used as example origins, not depots that served Harvey.
- Needs and donor offers are claims typed in by people. No money moves, no goods are tracked, and no contact details are kept, so nobody
  can be reached through the system.

## Responsible-data gaps (listed in the app)
- **No login.** Anyone who can reach the API can read it and take the actions; names on actions are free text.
- **No consent collection and no retention policy.** The system holds no consent records and has no deletion process.
- **Free-text notes** (tasks, needs, offers) are not read by the personal-data scan; the scan checks field names. Contact details in
  an offer are refused by a lexical check that will not catch every form.
- **A copy of the last view is kept in the browser** so the page opens offline: not encrypted, on that device until cleared.
- Map tiles come from OpenStreetMap's public server, which learns what area is viewed.

## Performance
- On one worker the full dashboard fails our load target (`/map/zones`, about 690 kB gzipped per refresh, is the bottleneck); four workers nearly pass.

## Not tested
- Phone layout, accessibility, and any user study with emergency managers. The copilot's model mode was not re-run for this
  submission to save API credit; its fixed-template mode was not part of the demo path.
