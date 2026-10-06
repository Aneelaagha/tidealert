# Last call

For each flagged zone: **how long until the latest moment a dispatch could still set out before its roads close.**

    last call = the zone's recorded cut-off time - the lead time you set (reply wait + decision + travel)

- `backend/app/services/last_call.py`, `GET /map/last-call?run_id=&at=&reply_min=&decision_min=&travel_min=`; page panel
  **Last call** (right column), a "Last call" row in the zone panel, and a **Play** button by the slider so the countdown can be
  watched tick down. Read-only; nothing is stored or sent.
- The **cut-off time is the isolation engine's own**: when it first finds every dry road out of the zone flooded (the stored
  evidence behind "cut off since" in the zone panel). A zone's states: **counting** (not cut off yet; time to last call), **passed**
  (last call has gone but the zone is not cut off yet), **cut off**, **reconnected**. Re-isolation after a reconnection counts down
  again. Tests pin the counts to supply access at the same time (133 cut off + 19 counting = 152 at 18:30 UTC; 88 cut off and 64
  reconnected on 28 Aug at 20:00) and each cut-off time to the safety service's "cut off since".
- The **lead time is not measured**: nothing in this system measures how long a crew needs. It is three boxes you fill in (default
  0), remembered in your browser, and the panel shows the sum. With none set, last call is the cut-off time itself.

## What this is not (and why a stronger version is not built)

- **It is a replay in hindsight.** The cut-off times are the engine's *recorded* results, standing in for a forecast. At a slider
  time the board reads some times later than the slider (that is what a countdown is), unlike the rest of the page, which never
  reads the future; rows that do say so (`hindsight`). A live system needs a river-stage forecast, which this project does not
  have, and its last calls could be no better than that forecast.
- **Per street-block zone, not per household.** Harvey has no households. The only households (33) are synthetic and none sits in
  a real basin, and no scenario zone has isolation evidence: **no run contains all three engines.** Putting synthetic households
  in Harvey would break the standing decision that synthetic households are not used for real events, so it was not done.
- **The listening engine is not wired to it.** No probe is scheduled at a last call and nothing is sent (the engine sends nothing
  anywhere; its latencies are drawn from a random distribution for the synthetic scenario, not measured). "Round-trip latency" is
  therefore not an input here.
- **"Cut off" means no dry road route out, as the engine finds it.** It does not mean the people cannot be reached by phone,
  neighbour, boat or aircraft, and **roads reopen**: in Harvey 64 zones are reconnected by 28 Aug 20:00 UTC. The page never says a
  zone is lost, a recovery, or unreachable by any channel (a test checks the wording).
- **Only as good as the flood surface and the road graph.** A zone the engine could not assess, or only "possibly" isolated, has
  **no last call** (unknown stays unknown): only zones with a recorded cut-off are listed.
- It does not show rescue requests. The project has no rescue-request data; NFIP claims are insurance claims, dated by day.

## Ideas it would take to go further (not built)

1. A river-stage forecast, so cut-off times are predictions and not hindsight.
2. Households inside a real event's zones that are real, or an explicit owner decision to allow synthetic ones in the mixed
   Harvey run, so the silence and listening engines and the isolation deadline can meet in one run.
3. A measured dispatch lead time (a depot-to-zone travel estimate needs a speed model and routes; depot access is feasibility
   only today).
