# signals-protocol

Shared **wire contracts** for the zndx signals federation. Vendored as a git
submodule:

```text
components/signals-protocol  →  git@github.com:zndx/signals-protocol.git  (trunk)
```

## Role in Signals

Signals pins this repo so the product SoR and the fleet share **one** protocol
source of truth. Engines (Ægir, Atelier, Gaius) and external peers generate
bindings from `proto/`; Signals publishes discovery for Atlas, OpenLineage, and
Ranger and adopts OIP mapping for multi-agent model ops.

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
