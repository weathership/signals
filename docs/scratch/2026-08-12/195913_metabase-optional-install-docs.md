# Docs: optional Metabase install for Signals operators

Updated shared ASL2 docs so Signals users can opt into AGPL Metabase without
vendoring it into the foundation tree.

## Touched

- `docs/current/src/operations/peer-integration.md` — full optional install:
  license, clone, path edit, install-systemd, signals.target vs signals,
  accept probes
- `infra/systemd/README.md` — optional Metabase section + command table
- `docs/current/src/operations/peer-unit-spec.md` — metabase accept marked done;
  operator one-liner
- `config/platform/peer-contract.json` — metabase notes + systemd install_hint/docs

## One-command reminder for operators

`systemctl start signals` ≠ Metabase  
`systemctl start signals.target` = foundation + ready + enabled peers
