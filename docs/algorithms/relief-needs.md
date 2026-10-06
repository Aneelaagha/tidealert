# Relief needs and pledges

Coordinators post what a zone needs, anyone can **pledge** a quantity against it, and the board ranks the needs by the zone's real
isolation state. This is a separate board from the operator-entered needs board and the donation portal (`needs.md`,
`donation-portal.md`); it lives under `/relief/...` and does not change them.

- `backend/app/services/relief_needs.py`, `backend/app/routes/relief.py`; models `ZoneNeed` (table `zone_needs`) and
  `NeedPledge` (`need_pledges`), migration `8dc7973503cf`; page panel `ReliefPanel.tsx`.
- `zone_needs` was an empty, unused scaffolding table; the migration reshapes it (and refuses to run if it has rows).

## What a pledge is, and is not

Everything is a **pledge**: an unverified test entry. The interface and the API never say delivered, received or fulfilled (tests
check both).
- **No payments** and no money item type. Goods only: water, food rations, shelter kits, blankets, medical kits.
- **No donor identity.** A pledge stores `quantity` and `created_at` and nothing else: no name, contact, IP or session
  (`tests/test_relief_needs.py` pins the column set). There is no leaderboard and no gamification.
- **No delivery tracking.** Nothing records that anything arrived anywhere.
- **No authentication.** `created_by` on a need is free text; anyone who can reach the API can post a need or pledge.
- **Replays refuse needs and pledges** (422, "off for replays because they would invent a relief history"), as task actions do. They
  work on the mixed run and any run that takes task actions.

## The data

`zone_needs`: run, zone, item (goods only), `quantity_needed` (> 0), `quantity_pledged` (>= 0), status
(`open` / `partial` / `filled` / `closed`), `created_by`, `is_synthetic`, timestamps. **Database check constraints** make a bad row
impossible: needed > 0, pledged >= 0, **pledged <= needed**, goods-only items, and `filled` only when pledged equals needed.

## Pledge semantics

`POST /relief/needs/{id}/pledges` locks the need row (`SELECT ... FOR UPDATE`, after flushing pending changes, the lesson of PR
#18), then: refuses a closed or filled need (409), refuses more than the **open quantity** with a 409 that states it ("only 30
litres are still open; cannot pledge 31"), otherwise records the pledge and sets the status in the same transaction (`partial`, or
`filled` when pledged equals needed). Two threads racing for the last unit get exactly one pledge; with the lock removed, 5 of 8
threads were told they succeeded and the pledge rows summed to 5 against a need of 1 (measured while building this).

## The sort

Most urgent first, from the zone's access state at the slider time (the safety service, the same states as everywhere else):
**cut off, may be cut off, not assessed, reconnected, dry route**, then the **largest open quantity**, then a fixed tie-break so the
order is deterministic. A zone whose access is not assessed is shown as "Not assessed" and ranks **above** reconnected and dry-route
zones, never below one: not knowing is not a reason to rank a need lower. A filled or closed need has no open quantity, so it sorts
after open needs in its group.

## The demo seed

`scripts/mixed_harvey_scenario.py` calls `relief_needs.seed_mixed` after it rebuilds the mixed run. The rule, fixed: at the
event's recorded peak (2017-08-27 20:00 UTC), take the zones the isolation engine finds **cut off** among the run's flagged zones,
order by recorded population (largest first, ties by zone id), and post water, food rations and medical kits for the first three,
each needing **one unit per recorded resident** (a placeholder ratio, not a measured need). They are flagged `is_synthetic`, created
by `script:mixed-scenario (synthetic)`, and shown with a "synthetic" tag. A rebuild replaces them (and clears pledges against
them) and leaves a coordinator's own needs alone. The run's content snapshot is unchanged by the seed.

## Limits

- **Unverified:** nobody checks a need or a pledge is real or that the goods exist.
- **No history:** the board is the current state. Moving the slider re-reads each zone's access, not the board's contents.
- **One worker:** the lock is a database row lock, so it holds across processes, but the page's load figures assume the
  documented one-worker setup (`docs/load-test.md`).
- Units (litres, rations, kits) are how the board counts, not measured quantities. The page cannot take a pledge to a zone's
  access or evacuate or route anything: it ranks and counts.
