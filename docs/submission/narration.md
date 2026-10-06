# Narration script (about 4 minutes)

Timed to the real demo moments. Click path in brackets; speak the lines in quotes. The two disclosures that must be spoken aloud are
marked **SAY**. Rehearse with the app on the Harvey replay (the default run) and the browser at desktop width. About 440 spoken words (about 3 minutes at a natural pace) plus the on-screen actions: roughly 4 minutes.

**0:00 to 0:25. Open.** [The page opens on the Harvey replay.]
"TideAlert answers one question during a river flood: which neighbourhoods have lost every road out, and who should we look at first.
**SAY:** What you're seeing is a replay of Hurricane Harvey, 2017, from recorded gauge data. It is not a live system, and there are no real
responders in this view."

**0:25 to 1:00. Start here.** [Click **Start here**.]
"One click opens Harvey at its worst moment, the afternoon of August 27th, frames the map and picks the first place to look. The headline
says it in one line: all 152 flagged street blocks are cut off at once. The list on the right ranks where to look first, and its rule is
printed under it. It's a display order, not a risk score."

**1:00 to 1:35. Why it says cut off.** [Click the first zone in the list; point at the zone panel.]
"This block lost its last dry road at 04:00 UTC. The evidence is here, with the rule that fired. The engine floods the road
network from the river's stage; a block is cut off when no dry road leads out. At the two gauges with an official flood map, the first road
floods thirty-seven to seventy-five minutes before the National Weather Service's minor-flood alarm."

**1:35 to 2:10. Supply and depot access.** [Click **Supply access**, then **Depot access**; pick a fire station.]
"Supply access colours every block by whether it can be reached. Depot access asks it from a fire station. This is feasibility only: whether a
dry route exists. It finds no route and gives no distance or time. Forty-nine blocks have no dry route from here, exactly the engine's own count."

**2:10 to 2:50. The mixed scenario.** [Click **Switch to the mixed scenario**; drag the slider to 28 August 03:45 UTC.]
"A replay can't be changed, so here is the mixed scenario: Harvey's real flood with synthetic responders. **SAY:** these responders and their
assignments are synthetic, scripted for the demo. Three were sent into blocks that were then cut off after they were assigned, and the system warns:
cut off after assignment."

**2:50 to 3:20. Needs and offers.** [Type a name; open a cut-off zone; enter a need; click **Donation portal**; offer; Mark received.]
"Operators can enter what a block needs, and donors can offer supplies. Both are typed in, labelled as claims, and no money moves and no contact
details are kept. An offer to a cut-off block is allowed but flagged: supplies may not reach it by road."

**3:20 to 3:45. Report and honesty.** [Click **Report**, then **Validation**.]
"The after-action report is built from stored rows and starts with the run's mode. The validation panel shows what held up and what did not. Against
insurance claims the engine reaches fourteen percent of the heaviest-claims areas; FEMA's static floodplain map reaches sixty-eight. We show that.
On Hurricane Helene it found no isolations, and the panel says why that proves nothing either way."

**3:45 to 4:05. Offline and close.** [Stop the server, wait for the banner; or reload with it stopped.]
"If the connection drops, the page keeps the last view, read-only, labelled with when it was saved. Everything is replayed history. Next is live gauges,
and validation against observed isolation."

## Optional beat: Last call (about 25 seconds; put it after "Start here")

[Open the Harvey replay, drag the slider to 18:30 UTC on 27 August. In the **Last call** panel type **60** in Travel. Press **Play**.]
"These blocks aren't cut off yet, but the engine's recorded results say they will be, at 19:45. If a crew needs an hour from the call to the
door, that's a number we set, not one we measured. Fifteen minutes of last call. **SAY:** in this replay the cut-off times are the engine's
recorded results, standing in for a forecast; a live system would need a river forecast. Watch it count down, and then the block is cut off:
no dry road route out. That says nothing about phones, and roads reopen."

Do **not** say: that these people can no longer be reached by any channel, that they become "a recovery", or that rescue requests arrive
afterwards (the project has no rescue-request data). It is per zone, not per household.

## Before recording

- Start the API and open `http://localhost:8000/ui/` (build the page first with `npm run build` in `frontend/`). Use a desktop-width browser.
- **Do not use the copilot's free-text box** (it calls the live model and spends credit). The script does not need it.
- Clear anything typed in earlier so the needs board starts empty: needs and offers entered on the mixed run persist in the database.
- The 2:50 beat writes to the mixed run (a need and an offer). Delete them afterwards, or rebuild the mixed run with
  `scripts/mixed_harvey_scenario.py` (needs and offers are kept across a rebuild, so delete them directly).
- Offline beat: stop the API (`pkill -f "uvicorn app.main"`), wait 5 to 10 seconds for the banner, or reload the page with it stopped to show
  "Opened offline: read-only". Restart it afterwards.
- Gauges view needs internet from the server (USGS). If USGS is unreachable it says so; skip that beat rather than show it empty.

## The exact click path

1. Open the page (Harvey replay). 2. **Start here**. 3. Click the first zone in **Needs attention**. 4. **Supply access**. 5. **Depot access**, pick a fire station.
6. **Switch to the mixed scenario**, drag the slider to 2017-08-28 03:45 UTC. 7. Type a name in the Operator bar, open a cut-off zone, enter a need (water 40),
**Donation portal**, offer, Mark received. 8. **Report**. 9. **Validation** (Harvey tab, then Helene tab). 10. **Gauges** (optional). 11. Stop the server for the offline banner.
