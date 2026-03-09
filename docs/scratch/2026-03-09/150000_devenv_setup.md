# devenv Setup — Initial Configuration

## Summary

Established the signals-360 development environment with devenv, covering infrastructure services, ASF component submodules, and forward-looking architecture tooling.

## What was done

### devenv.nix
- PostgreSQL 16 with Apache AGE (graph queries) and pg_cron (scheduled jobs)
- Kerberos KDC (KRBTEST.COM realm, port 8848) with idempotent init script
- Languages: Rust, Python 3.12 (uv), Java 21 (Maven), TypeScript/JavaScript
- ASF build deps: cmake, ninja, gcc, protobuf, flatbuffers, cyrus_sasl, openssl_3
- K8s stack: kubectl, helm, tilt, k9s, k3d, podman
- Deployment: awscli2, opentofu, ansible, zarf, conftest, cloudflared
- WASM tooling: wasmtime, wasm-pack, wasm-bindgen-cli, binaryen
- Documentation: mdbook with d2, katex, mermaid preprocessors
- Utilities: gh, jq, grpcurl, dbmate, presenterm, imagemagick

### ASF Component Submodules (components/)
Seven Apache project forks from rch GitHub account, all on `rch/signals` branch:
- atlas, ranger, kudu, impala, iceberg, airflow, nifi

### KDC Init Script (scripts/kdc-init.sh)
Idempotent MIT Kerberos initialization adapted from Kudu's MiniKdc patterns:
- Principals: postgres/localhost (service + keytab), signals (user, pw: signals)
- Config stored in .devenv/kdc/ (gitignored)

### Documentation Structure
- mdbook at docs/current/ (book.toml + src/)
- Work notes at docs/scratch/YYYY-MM-DD/

## Architecture Notes

Future web interface design:
- Ghostty WASM terminal (browser-embedded, bottom half)
- gRPC engine with mistral-vibe-inspired agent (server-side, Rust)
- HoloViews/Datashader/Dask visualization stack (agent-mediated, top half)
- Instructions transit gRPC; Dask/Datashader recompute views on demand
