# Needs board

What an **operator says** each zone needs, as of a time. Typed in by a person, never measured, inferred, matched or
routed. Every entry says who entered it and when, and the page says so wherever it is shown.

- `backend/app/services/needs.py`, `backend/app/routes/needs.py`: `GET /needs?run_id=&at=` and `POST /needs`.
- `backend/app/models/need_event.py`: the append-only `need_events` table (migration `7e7b75c5ae11`). The older
  `zone_needs` table (current value only, no run, no history) is unused and left as it was.

## Where it works

| Run | Entries |
|---|---|
| Harvey replay, the 2024 replay | **Refused** (422), with the reason shown on the page. Entered needs would be typed-in claims added to a record of a real event, and the replay's Cases are checked against a baseline. |
| Mixed Harvey run | Accepted. Real flood and isolation results, synthetic people, and now typed-in needs, all labelled MIXED. |
| Scenarios, live runs | Accepted. |

Needs are keyed by run. The replay and the mixed run share zones, so without this a need entered on the mixed run
would appear on the replay; a test checks it does not.

## The data

Entries are events: `requested`, `fulfilled`, `withdrawn`, each with an item (water, food, medical, shelter,
blankets, boat, vehicle, other), a whole-number quantity, the operator's name, a time on the run's clock and an
optional note. A zone's open need for an item at time T is requested − fulfilled − withdrawn over the entries up to
T, so moving the slider earlier reads only what had been entered by then. Nothing is edited in place.

**Rules** (like task actions): the operator name is required (there is no login, so it is free text); an entry is
stamped with the slider time, inside the run's window, and not earlier than that item's latest entry in the zone;
quantity is 1 to 1,000,000; you cannot fulfil or withdraw more than is open (409); a zone must be part of the
run's view; a note is at most 300 characters. Zone rows are locked while an entry is checked, so concurrent entries
cannot both spend the same quantity (a race test shows 6 threads fulfilling 1 each of 3 open: exactly 3 succeed).

## The board and the zone panel

- **Board strip** (under the map): open needs by item with the number of zones, and how many zones with open needs
  are **cut off** (or may be) according to the isolation engine's stored output (the same state as supply access).
  Cut-off zones are buttons that open the zone. On a replay it says it is off and why, in the server's words.
- **Zone panel:** that zone's items, the entry history, the zone's access, and the entry form.

## What it does not do

- It does not know what a zone needs. Values are what people typed; nothing checks them against any other source.
- No matching of needs to supplies beyond donors' own offers (`donation-portal.md`), no routing, no allocation, no priorities.
- No login: anyone who can reach the API can enter or read needs. Notes are free text and the personal-data scan
  checks field names, so personal details typed into a note would not be caught (listed as a gap in Data & ethics).
- "Cut off" means the engine finds every road route out flooded; it does not say a need could not be met by boat or
  air.
- Needs entered for the demo are example inputs by whoever typed them, not facts about 2017.
- Entries made on the mixed run persist across a rebuild of it (`scripts/mixed_harvey_scenario.py` clears only its
  Cases, tasks and responders). Deleting the run deletes its needs.
