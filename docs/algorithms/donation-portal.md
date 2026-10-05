# Donation portal

Donors **offer supplies** against the needs on the board (`needs.md`), and an operator records what arrived. It moves
no goods, takes **no money**, checks no offer is real, and stores **no contact details**. An offer is a claim typed
in by a donor, exactly as a need is a claim typed in by an operator.

- `backend/app/services/pledges.py`, `POST /pledges` and `POST /pledges/{id}/close` (`backend/app/routes/needs.py`).
- `backend/app/models/pledge.py`: the `pledges` table (migration `a28b563698ed`). Offers appear in `GET /needs` as
  `pledges` per zone, with `pledged` and `unpledged` per item.
- Page: a **Donation portal** drawer opened from the Needs board strip, and the zone panel's Needs block lists the
  zone's offers.

## Where it works

Same rule as the needs board: **refused on a replay** (422, the reason shown), accepted on the mixed run, scenarios
and live runs. Offers are keyed by run, so an offer on the mixed run never appears on the Harvey replay.

## Rules

- **An offer answers an open need.** It must be for an item an operator has requested in that zone and that is still
  open, and at most what is open **and not already offered** (409 otherwise). Offered quantity is spoken for: fulfilling
  or withdrawing a need cannot eat into an open offer (409).
- **Time:** offers and closings are stamped with the slider time inside the run's window; an offer cannot predate the
  need's latest entry, a closing cannot predate its offer. A past time reads the offers open then.
- **Closing** (an operator, under the name in the Operator bar): **received** records a `fulfilled` need entry of that
  quantity in the same transaction ("received from pledge by <donor>"); **withdrawn** returns the quantity to the
  unpledged need. A pledge closes once (409 after).
- **Donor name** (required, at most 60 characters) is shown with the offer. It, and the note, are refused if they
  contain an `@`, a link, or a run of seven or more digits. That check is **lexical**: it catches the obvious forms of
  contact details, not every form.
- Zone rows are locked while an offer or closing is checked (race tests: 6 threads offering 1 each against 3 open
  succeed exactly 3 times; 5 threads receiving one pledge succeed once and fulfil once).

## Cut-off zones

An offer to a zone the isolation engine finds cut off is **allowed and flagged**, never hidden: the portal row says
"ZONE CUT OFF", that the engine finds every road route out flooded since T, and that supplies may not reach it by
road and the page can't say how else they could. The board strip counts offers to cut-off zones.

## What it does not do

- No payments or money of any kind. No goods tracking, no verification of donors or offers, no reputation.
- No contact details, so an operator cannot reach a donor through this system. A real deployment would need
  verified contact, consent and retention rules; none exist here (see Data & ethics).
- No matching beyond the offer itself; no routing and no allocation; no delivery times or vehicles.
- No login: anyone can offer, and anyone who enters an operator name can close an offer.
- Offers entered for a demo are example inputs, not facts about 2017.
