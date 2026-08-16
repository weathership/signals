# Protocol push + peer data-product playbook

Pushed `signals-protocol` so Gaius can pin trunk for prospects Metaflow.

## Protocol (zndx/signals-protocol)

- `SignalKind.TX_ID_NOT_UUIDV7 = 5` + `specification/protocol/tx_id.md`
- `data_products.md` — federation contract (identity, details/tx/hx, RustFS,
  CE, history-review, what peers must not do)
- Sentinel spec: resource-class queues (not `root.{project}`)

## Signals playbook

`docs/current/src/operations/peer-data-products.md` — what Gaius/Ægir/Atelier
need to maintain a product on shared RustFS without a second warehouse.

Signals tree still has a large uncommitted warehouse/Polaris/C2 working
set; protocol is what Gaius pins first.
