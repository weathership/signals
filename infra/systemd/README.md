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

Metabase is **optional**. Core Signals does not ship or require it. Operators who
want a federated **dashboard** peer install a separate AGPL product tree and
opt into `metabase.service` under `signals.target`.

| Tree | License | Role |
|------|---------|------|
| `weathership/signals` (this repo) | Apache-2.0 | Foundation + critical plane |
| Metabase product checkout (separate) | AGPL-3.0 | External `dashboard` engine |

Metabase **must not** be a submodule, jar, or source copy inside signals.
Integration is:

1. **Process** — `metabase.service` points `WorkingDirectory=` / `ExecStart=` at
   the AGPL checkout (`scripts/systemd_start.sh` / `systemd_stop.sh` live there)
2. **Wire** — shared `signals-protocol` submodule in *that* tree; gRPC `:50451`
3. **Platform** — Metaflow / Airflow / Eventing / YK consumed via published endpoints

Static-linking or shipping AGPL sources inside ASL2 artifacts is out of scope
and legally undesirable; keep the boundary at the OS process + network.

Full operator guide (clone → path edit → enable → accept):
[Peer integration — External engines: Metabase](../../docs/current/src/operations/peer-integration.md#external-engines-metabase-agpl).

### Optional: add Metabase to the group

```bash
# 1) Product tree exists and answers health + Status on its own
#    (see that repo's README.engine.md)

# 2) Edit infra/systemd/metabase.service absolute paths if needed:
#    User/Group, WorkingDirectory, ExecStart/ExecStop → AGPL scripts

# 3) From this signals checkout:
just install-systemd --peers metabase --enable

# 4) Group bring-up (includes Metabase when enabled)
sudo systemctl start signals.target

# 5) Accept
systemctl is-active metabase.service
grpcurl -plaintext 127.0.0.1:50451 zndx.engine.v1.Engine/Status
curl -sf http://127.0.0.1:3200/api/health
just lattice-ci --require metabase
```

| Command | Starts Metabase? |
|---------|------------------|
| `systemctl start signals` | **No** — foundation unit only |
| `systemctl start signals.target` | **Yes**, if `metabase.service` is enabled for the target |
| `systemctl start metabase` | Yes (peer alone; still `After=signals-ready`) |

## Install (system units)

Paths in samples default to `/home/rch/local/src/...`. Edit `WorkingDirectory=` /
`ExecStart=` / `User=` if your layout differs.

```bash
cd ~/local/src/wxs/signals

# Preferred installer (foundation only)
just install-systemd --enable --start

# Later: install peer samples (enable only after peer-unit-spec accept)
just install-systemd --peers gaius,aegir,atelier,metabase --enable

systemctl list-dependencies signals.target
just signals-ready
just lattice-ci --require gaius,aegir,atelier,metabase   # whichever enabled
```

Manual equivalent (foundation):

```bash
sudo install -m 644 infra/systemd/signals.target \
  infra/systemd/signals.service \
  infra/systemd/signals-ready.service \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now signals.target
```

Foundation `ExecStart` uses repo wrappers so Postgres lattice stop is correct
(never bare `devenv processes down` alone).

**Peer pattern (required before enable):** each peer tree owns
`scripts/systemd_start.sh` / `systemd_stop.sh` that block until
`Engine/Status` on the contract port (Metabase is the reference implementation).
Sample units for gaius/aegir/atelier still point at temporary `just up` shells
until those peer sessions land — then update units to absolute wrapper paths.

Full ops for every peer:
[docs/current/src/operations/peer-integration.md](../../docs/current/src/operations/peer-integration.md).

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
