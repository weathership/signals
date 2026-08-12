# Systemd group control — `signals.target`

Sample units for lab hosts that bring **Signals foundation** up with optional
federated peer engines (Ægir, Atelier, Gaius, Synth) and **external** engines
(e.g. AGPL Metabase) under one group target.

## Host requirements

| Tool | Why | Lab install |
|------|-----|-------------|
| **`just`** | Foundation/peer scripts invoke recipes | `/usr/local/bin/just` (system-wide; not devenv-only) |
| **`kubectl`** | `signals-ready` probes Knative Eventing Broker | `/usr/local/bin/kubectl` + readable `~/.kube/rke2.yaml` |
| **`grpcurl`** | `just lattice-ci` Engine/Status probes | `/usr/local/bin/grpcurl` |

```bash
# just — official prebuilt
curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh \
  | sudo bash -s -- --to /usr/local/bin

# kubectl — Kubernetes release binary (version may match lab RKE2)
sudo curl -fsSLo /usr/local/bin/kubectl \
  "https://dl.k8s.io/release/v1.31.6/bin/linux/amd64/kubectl"
sudo chmod +x /usr/local/bin/kubectl

# grpcurl — lattice-ci Status RPC (fullstorydev release)
curl -fsSL \
  "https://github.com/fullstorydev/grpcurl/releases/download/v1.9.3/grpcurl_1.9.3_linux_x86_64.tar.gz" \
  | sudo tar -xz -C /usr/local/bin grpcurl
sudo chmod +x /usr/local/bin/grpcurl

env -i PATH=/usr/local/bin:/usr/bin:/bin just --version
env -i PATH=/usr/local/bin:/usr/bin:/bin kubectl version --client
env -i PATH=/usr/local/bin:/usr/bin:/bin grpcurl --version
```

Foundation units call repo wrappers (not bare `just` in the unit file):

- `scripts/systemd_foundation_start.sh` — idempotent up / already-ready
- `scripts/systemd_foundation_stop.sh` — `just down`
- `scripts/systemd_signals_ready.sh` — poll `just signals-ready`

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

# Preferred installer (foundation only)
just install-systemd --enable --start

# Later: install peer samples (enable only after peer-unit-spec accept)
just install-systemd --peers gaius,metabase --enable

systemctl list-dependencies signals.target
just signals-ready
just lattice-ci
```

Manual equivalent:

```bash
sudo install -m 644 infra/systemd/signals.target \
  infra/systemd/signals.service \
  infra/systemd/signals-ready.service \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now signals.target
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
