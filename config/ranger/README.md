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

## Day-one setup

```bash
devenv tasks run ranger:db-setup   # materialize install.properties + JDBC + roles
devenv tasks run ranger:build      # Maven security-admin + tagsync
# then unpack admin package and run setup.sh against .devenv/ranger/conf/install.properties
```

Default admin passwords in `install.properties` are **dev-only** (`Admin123`).

See project plan Phase 3 and `docs/current/src/components/ranger.md`.
