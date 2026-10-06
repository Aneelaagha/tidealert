# Relief needs and pledges API

Test pledges: no payments, no identity, no delivery tracking, no authentication. See `docs/algorithms/relief-needs.md`.

| Route | What it does |
|---|---|
| `GET /relief/needs?run_id=&at=` | The run's needs with each zone's access state at `at`, most urgent first. |
| `POST /relief/needs` | Post a need. Body: `run_id, zone_id, item_type, quantity_needed, created_by, at?`. |
| `POST /relief/needs/{id}/pledges` | Pledge a quantity. Body: `quantity, at?`. |
| `POST /relief/needs/{id}/close` | Close a need to further pledges. Body: `at?`. |

All three writes are reviewed write routes (`app.services.data_policy.WRITE_ROUTES`); `GET /relief/needs` is in the response scan
for personal fields.

## `GET /relief/needs`

`{ run_id, mode, at, label: "Test pledges. No payment is processed.", writable, blocked_reason, items, access_labels, needs: [...] }`.
`writable` is false on a replay and `blocked_reason` says why. Each need:
`{ id, run_id, zone_id, zone_name, item_type, item_label, unit, quantity_needed, quantity_pledged, quantity_open, percent, status,
created_by, is_synthetic, created_at, access: { state, label, since } }`. `state` is one of `isolated`, `possibly_isolated`,
`not_evaluated`, `reconnected`, `reachable`, with the labels "Cut off", "May be cut off", "Not assessed", "Reconnected, not a
guarantee", "Dry route". A pledge has no identity fields.

## Errors

| Status | When |
|---|---|
| 404 | the run, zone or need does not exist |
| 422 | a replay (plain explanation); an item that is not goods; a quantity that is not a whole number in range; no `created_by`; a zone outside the run's view; a time outside the run's window |
| 409 | a pledge on a closed or filled need, or for more than is open (the detail states the open quantity); closing a closed need |
