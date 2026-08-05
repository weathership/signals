# Stack plan kickoff — submodules, AGE/Atlas, Kerberos, Kudu, Ranger scaffold

## Done in this change set

### Kerberos (ZNDX realism)
- Default realm: `VISTA.ZNDX.ORG` (location)
- Host FQDN: `tinybox.dev.vista.zndx.org` (host.posture.location.tld)
- KDC still loopback :8848
- SPNs: postgres/impala/HTTP/kudu + user `signals@`
- Updated: `scripts/kdc-init.sh`, `devenv.nix` env, BDD `health_kerberos.feature`, ops docs
- **Requires** `devenv tasks run signals:kdc-reset` on existing checkouts

### Atlas coexistence + AGE process hardening
- Signals Atlas HTTP **:21010** (aegir keeps :21000)
- AGE isolation unchanged: PG :5455 / DB `signals` / graph `atlas_graph`
- Process: materialize conf with `$PGPORT`, `pg_isready`, conf under `$ATLAS_HOME/conf`
- Defaults: base.conf, config.py, preflight, features/environment, .env.example

### Kudu path
- Default build/runtime: `components/kudu` (not `$HOME/local/src/asf/kudu`)
- `KUDU_BUILD` env still allowed as override

### Ranger scaffold
- Postgres initial DB `ranger`
- `config/ranger/README.md`, expanded `docs/.../ranger.md`
- Preflight port 6080 reserved

### DX
- Just recipes: kudu-build, impala-bootstrap/build, atlas-build, kdc-reset, stack-build

## Next
1. Finish submodule init; pin atlas → `4326a529`, impala tip after review
2. `kudu:build-cpp` / `impala:bootstrap` + `impala:build` from submodules
3. `atlas:build` + smoke on :21010
4. Ranger admin/tagsync tasks and processes
5. Bootstrap empty `weathership/impala_fdw` then submodule add
