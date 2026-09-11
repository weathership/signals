# Quick Start

## Prerequisites

- Linux workstation (Impala, Kudu, and the RKE2 critical plane)
- [devenv](https://devenv.sh/) + Nix; [direnv](https://direnv.net/) recommended
- [just](https://github.com/casey/just), `kubectl`, `grpcurl` on `PATH`
- Recurse submodules on clone

## Bring-up

```bash
git clone --recurse-submodules git@github.com:weathership/signals.git
cd signals
devenv shell

# One-time native builds if this machine has never built them
devenv tasks run kudu:build-cpp
devenv tasks run impala:build

cp .env.example .env
just up
just signals-ready
```

`just up` starts PostgreSQL 16 + AGE (`:5455`), Kerberos, RustFS,
Polaris, Atlas, Ranger, Kudu, Impala, signals-ui, and preflights
YuniKorn, Knative, Metaflow, and Airflow on RKE2.

Open **http://127.0.0.1:9889** — that is the control plane.

```bash
just kinit
just kerberos-status    # Impala HS2 GSSAPI OK
just lattice-ci
just test               # pytest tests/
just behave             # tier-0 BDD; SIGNALS_BDD_TIER1=1 for the live stack
just docs-serve
```

## Attach a peer

```bash
just install-systemd --peers gaius,aegir,atelier --enable
sudo systemctl start signals.target
just lattice-ci --require gaius,aegir,atelier
```

A new engine implements `zndx.engine.v1` on its lattice port, waits on
`signals-ready.service`, Announces, and consumes Metaflow, Atlas, and
the warehouse. Contract:
[`config/platform/peer-contract.json`](https://github.com/weathership/signals/blob/trunk/config/platform/peer-contract.json).
Walkthrough: [Peer integration](./operations/peer-integration.md).

## Classify columns (optional)

The in-tree `sigint` pipeline samples Impala, fuses evidence, and
writes Atlas tags:

```bash
just tag-dry-run default.my_table
just tag default.my_table
```

See [Metadata Tagging](./architecture/meta-tagging.md).

## Next

- [System Overview](./architecture/overview.md)
- [signals-protocol](./architecture/signals-protocol-core.md)
- [Query engine](./architecture/query-engine.md)
- [devenv](./operations/devenv.md)
