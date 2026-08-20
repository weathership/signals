# Adopt ServerQuery: remotes + primary UI

Pin `signals-protocol` at `25c54ab` (Status.surfaces + ServerQuery including
QUEUES). Regen stubs. Signals engine now answers:

- `Status.surfaces` — `kind=primary` `SIGNALS_UI_URL` (`:9889`)
- `ServerQuery REMOTES` — `git remote -v` + HEAD (origin, upstream, …)
- `ServerQuery SURFACES` — same list as Status
- `ServerQuery PEERS` — peer-contract lattice ports, skip self

Do not invent peer UI URLs. Empty remotes when the checkout is not a repo.
