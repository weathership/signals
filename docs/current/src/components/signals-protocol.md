# signals-protocol

Shared **wire contracts** for the zndx signals federation. Vendored as a git
submodule:

```text
components/signals-protocol  →  git@github.com:zndx/signals-protocol.git  (trunk)
```

## Role in Signals

Signals pins this repo so the product SoR and the fleet share **one** wire
contract. Engines (Ægir, Atelier, Gaius) and external peers generate bindings
from `proto/`; Signals publishes discovery for Atlas, OpenLineage, and Ranger
and adopts OIP mapping for multi-agent model ops.

The protocol is **not finished foundation** — it grows as peer engines surface
needs that belong on a shared path (additive within a version). Signals does
not replace peer engine design; it holds the pin and platform attachment.
See [How the federation contract evolves](../architecture/signals-protocol-core.md#how-the-federation-contract-evolves).

See [Signals protocol core](../architecture/signals-protocol-core.md).

## Layout

| Path | Content |
|------|---------|
| `proto/zndx/engine/v1/engine.proto` | `Complete`, `Status`, `Remediate` |
| `specification/protocol/engine_grpc.md` | Human spec + OIP mapping notes |

## Bump

```bash
git -C components/signals-protocol fetch origin
git -C components/signals-protocol checkout origin/trunk
git add components/signals-protocol
git commit -m "chore: bump signals-protocol"
```

Protocol **changes** land as PRs on `zndx/signals-protocol` (additive within a
version), then submodule pin here — never fork a second proto tree in Signals.
