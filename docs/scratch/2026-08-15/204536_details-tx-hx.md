# Warehouse names: details / tx / hx

Locked names (not `facts`, not `history`):

- `details` — fact log `(e, a, v, t, op)`
- `tx` — event header (`tx_id`)
- `hx_exchange` / `hx_reasoning` — keyed to `tx_id`

Current inventory is a projection of `details`, not a table.
8 tests green.
