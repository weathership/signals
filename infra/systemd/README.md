# Systemd group control — `signals.target`

Sample units for lab hosts that bring **Signals foundation** up with optional
federated peer engines (Ægir, Atelier, Gaius, Synth) and **external** engines
(e.g. AGPL Metabase) under one group target.

## Topology

```text
multi-user.target
  └── signals.target
        ├── signals.service          # just up / just down  (foundation)
        ├── signals-ready.service    # oneshot: just signals-ready until exit 0
        ├── aegir.service            # After=signals-ready.service
        ├── atelier.service
        ├── gaius.service
        ├── synth.service
        └── metabase.service         # EXTERNAL AGPL tree — not vendored here
```

Peers are **peer-to-peer** with each other (no ordering edges). All order after
**`signals-ready.service`**, not merely after `signals.service` process start.

## License boundary (Metabase)

| Tree | License | Role |
|------|---------|------|
| `weathership/signals` | Apache-2.0 | Foundation + critical plane |
| `~/local/src/agpl/metabase` | AGPL-3.0 | External `dashboard` engine |

Metabase **must not** be a submodule, jar, or source copy inside signals.
Integration is:

1. **Process** — `metabase.service` `WorkingDirectory=` points at the AGPL checkout
2. **Wire** — shared `signals-protocol` submodule in *that* tree; gRPC `:50451`
3. **Platform** — Metaflow / Airflow / Eventing / YK consumed via published endpoints

Static-linking or shipping AGPL sources inside ASL2 artifacts is out of scope
and legally undesirable; keep the boundary at the OS process + network.

## Install (system units)

Paths default to `/home/rch/local/src/...`. Edit `WorkingDirectory=` /
`Environment=` if your layout differs.

```bash
cd ~/local/src/wxs/signals

# Review and adjust paths/user in the unit files first
sudo install -m 644 infra/systemd/signals.target \
  infra/systemd/signals.service \
  infra/systemd/signals-ready.service \
  /etc/systemd/system/

# Peers (enable only what you run on this host)
sudo install -m 644 infra/systemd/aegir.service \
  infra/systemd/atelier.service \
  infra/systemd/gaius.service \
  infra/systemd/synth.service \
  infra/systemd/metabase.service \
  /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable signals.target signals.service signals-ready.service
# Optional peers:
sudo systemctl enable aegir.service atelier.service gaius.service synth.service metabase.service

sudo systemctl start signals.target
systemctl list-dependencies signals.target
just signals-ready   # from signals tree; or: systemctl status signals-ready.service
```

`ExecStart` uses `just up` / `just down` so Postgres lattice stop is correct
(never bare `devenv processes down` alone).

## User units alternative

For personal machines without linger, copy the same files to
`~/.config/systemd/user/`, drop `User=`/`Group=`, and use
`systemctl --user enable …`. Enable linger for boot-without-login:

```bash
loginctl enable-linger "$USER"
```

## Contract file

Machine-readable endpoints + peer lattice:

`config/platform/peer-contract.json`

Docs: [Peer integration](../../docs/current/src/operations/peer-integration.md)
