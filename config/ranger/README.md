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
- [ ] `install.properties` / admin site XML
- [ ] `devenv` tasks: `ranger:build`, `ranger:db-setup`
- [ ] processes: `ranger-admin`, `ranger-tagsync`
- [ ] Impala plugin + SIGDG tag policies

See project plan Phase 3 and `docs/current/src/components/ranger.md`.
