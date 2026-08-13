# gaius.service wrappers installed

**Date:** 2026-08-12

Gaius peer session landed `scripts/systemd_{start,stop}.sh` and
`zndx.engine.v1.Engine` Status. Sample unit now Exec* those scripts.

```bash
just install-systemd --peers gaius --enable
```

Installed and enabled. `systemctl start gaius` / `signals.target` not run here:
live `:50051` is an older gaius-engine (no lattice face yet). Recycle
`gaius-engine` then:

```bash
grpcurl -plaintext 127.0.0.1:50051 zndx.engine.v1.Engine/Status
just lattice-ci --require gaius
```

Status body proven on an ephemeral bind (`project=gaius`, `cognition`).
