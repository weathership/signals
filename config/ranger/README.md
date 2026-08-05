# Ranger devenv configuration (signals)

Scaffold for Apache Ranger against signals Postgres + Atlas.

| Item | Value |
|------|--------|
| Postgres | `localhost:5455`, database **`ranger`** |
| Admin UI | `http://localhost:6080` (planned) |
| Atlas (TagSync source) | `http://localhost:21010` |
| Kerberos realm | `DEV.VISTA.ZNDX.ORG` |
| TagSync Atlas user | `rangertagsync` (see `config/atlas/users-credentials.properties`) |

## Status

- [x] Postgres `ranger` DB declared in `devenv.nix`
- [x] `config/ranger/install.properties` (Postgres :5455, SIMPLE auth, Atlas TagSync target)
- [x] `devenv` tasks: `ranger:build`, `ranger:db-setup`
- [ ] processes: `ranger-admin`, `ranger-tagsync`
- [ ] Impala plugin + SIGDG tag policies

## Day-one setup (local Ranger, not Impala CDP tarball)

Impala is rewired via `config/impala/impala-config-local.sh` so it does **not** download
or use the CDP `ranger-*-admin` package. Instead:

| Knob | Value |
|------|--------|
| `RANGER_VERSION_OVERRIDE` | `3.0.0-SNAPSHOT` (local Maven) |
| `RANGER_HOME_OVERRIDE` | `$PWD/.devenv/ranger/admin` |

```bash
devenv tasks run ranger:db-setup   # install.properties + JDBC + roles
devenv tasks run ranger:build      # JDK 11 → install into .devenv/m2 (project-local)
devenv tasks run ranger:install    # unpack admin under .devenv/ranger/admin
(cd .devenv/ranger/admin && ./setup.sh)
```

**Maven isolation:** devenv sets `SIG_MAVEN_REPO=$PWD/.devenv/m2` and `MAVEN_ARGS=-Dmaven.repo.local=…`
so Ranger/Impala/Atlas builds do **not** write SNAPSHOTs into `~/.m2`.

Impala bootstrap/build copies `config/impala/impala-config-local.sh` into the submodule
(`bin/impala-config-local.sh`, gitignored) so `IMPALA_RANGER_VERSION` matches those jars.

Default admin passwords in `install.properties` are **dev-only** (`Admin123`).

See project plan Phase 3 and `docs/current/src/components/ranger.md`.
