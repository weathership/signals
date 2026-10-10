# Semantica on the lattice

Semantica joins from its own tree (`devenv up` in `~/local/src/oss/semantica`), the way Metabase does.

- Engine `zndx.engine.v1` on `:50751`. Product HTTP on `:8070` (`:8000` is optillm on this host).
- `config/platform/peer-contract.json` lists `engine_grpc_lattice.semantica` and a `peers[]` row. The waffle reads Signals `ServerQuery PEERS`, then `Status.surfaces`.
- Advertise host is `tinybox.dev.vista.zndx.org`. Primary surface: `http://tinybox.dev.vista.zndx.org:8070/`.
- Announce is accepted by Aegir `:50151`. The Signals engine still answers Announce `UNIMPLEMENTED`.
- No systemd unit yet. `lattice-ci` skips the peer when `:50751` is not listening.
