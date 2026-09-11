# Operations Guide

How to run the Signals hub on a workstation or lab host.

1. **[Development Environment](./devenv.md)** — devenv shell, `just up`, tasks
2. **[Peer integration](./peer-integration.md)** — join the lattice
3. **[Secrets](./secrets.md)** — SecretSpec, dotenv, keytabs
4. **[Services](./services.md)** — PostgreSQL (AGE, pg_cron)
5. **[Kerberos](./kerberos.md)** — project-local KDC (`DEV.VISTA.ZNDX.ORG`)
6. **[Storage and backup](./storage-and-backup.md)** — `SIGNALS_DATA_ROOT`, stamps
7. **[Peer data products](./peer-data-products.md)** — warehouse facts
8. **[Peer unit acceptance](./peer-unit-spec.md)** — `signals.target` and lattice-ci

```bash
devenv shell
just up
just signals-ready
just kinit
just lattice-ci
just test
just docs-serve
```

Infrastructure provisioning (AWS, Zarf, Tilt) is under
[Infrastructure](../infrastructure/overview.md).
