# UUIDv7 tx_id + TX_ID_NOT_UUIDV7

Warehouse mints RFC 9562 v7 (`signals.uuidv7.mint`, monotonic rand_a).
`epoch_day` still the Kudu range key (derived from the v7 timestamp when set).

Non-v7 ids raise `NonUuid7TxId`. Protocol additive: `SignalKind.TX_ID_NOT_UUIDV7 = 5`.
`signals.ops.tx_remediate` builds `RemediationRequest` for the **source** engine
(`capability=reauthor`). Signals does not rewrite a foreign id.

13 tests green. Submodule `components/signals-protocol` is dirty until that
repo commits the proto/spec and Signals bumps the pin.
