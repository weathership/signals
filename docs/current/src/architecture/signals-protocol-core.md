# Signals protocol core

Signals is the **system of record** and the **central discovery surface** for the
zndx federation: lineage, governance metadata, and authz decision inputs live
here. Federated engines (Ægir, Atelier, Gaius, and **external** peers such as
Metabase) operate on the fleet; they **discover and call** centralized services
instead of each growing a private catalog, lineage store, or policy engine.
**Hermes Agent** is a multi-agent runtime we integrate with (**plugins first,
not a core fork for now**) for **reasoning-enabled memory** and **context
compaction**, with Weathership as the path to an
[official Hermes memory provider](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory-providers).
The federated fleet is already a **healthy superset** of Hermes’s product
surface (governance SoR, multi-engine federation, DST, nascent SAE/CLT
interpretability, persistent homology / Ollivier–Ricci topology)—capabilities
Hermes may never fully adopt in-tree.

Wire contracts live in the shared submodule
[`components/signals-protocol`](https://github.com/zndx/signals-protocol)
(`git@github.com:zndx/signals-protocol.git`, branch `trunk`). Changes land in
that repo first (additive-only within a version), then propagate by submodule
bump — one proto, every adopter.

## Layers

```text
  UIs / external engines          Federated engines (OIP + zndx.engine.v1)
  ┌──────────────┐                ┌─────────┬──────────┬─────────┐
  │ Marquez-web  │                │  Aegir  │ Atelier  │  Gaius  │
  │ Metabase*    │                │ :50151  │ :50251   │ :50051  │
  │ Atlas UI     │                └────┬────┴────┬─────┴────┬────┘
  └──────┬───────┘                     │         │          │
         │  HTTP                       │  gRPC federation face
         │  /api/v1  /api/atlas        │  + OIP ModelInfer (horizon → now)
         ▼                             ▼
  ┌────────────────────────────────────────────────────────────┐
  │  SIGNALS (this product)                                     │
  │  · Atlas :21010  governance SoR + OpenLineage /api/v1       │
  │  · Ranger        tag/resource authz from Atlas tags         │
  │  · Marquez-web   OL UI (proxy only; no Marquez DB)          │
  │  · components/signals-protocol  shared protos + specs       │
  │  · components/hermes-agent      agent runtime (plugins)     │
  │  · PG/AGE + Kudu/FDW scale path                             │
  └────────────────────────────────────────────────────────────┘
         ▲
         │  MemoryProvider + context engine plugins
         │  (Weathership → official Hermes memory service)
  ┌──────┴───────┐
  │ Hermes Agent │  tools / hooks / multi-agent ops
  └──────────────┘

  * AGPL Metabase (and similar) are *external* federation peers: they consume
    catalog/lineage/authz discovery; they do not become SoR.
```

| Concern | Authority | Client surface |
|---------|-----------|----------------|
| Governance types & classifications | **Atlas** on `signals` PG + AGE | `/api/atlas/*` |
| Runtime lineage (Job/Run/Dataset) | **Same Atlas process** + `signals_ol` | `/api/v1/*` (OpenLineage + Marquez-compat) |
| Authorization decisions | **Ranger** (Atlas tags as input) | Ranger REST / plugins; policy evaluate via discovery |
| Human OL UI | **Marquez-web** | `:3000` → proxies `/api/v1` only |
| Agent memory + compaction | **Weathership** plugins on Hermes | `MemoryProvider` + context engine ([plugins](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins)) |
| Engine-to-engine inference | **`zndx.engine.v1`** | `Complete` / `Status` / `Remediate` |
| Heterogeneous model serving | **KServe OIP** + signals-protocol mapping | `ModelInfer` / readiness; authz + provenance on the wire |
| GPU co-tenancy | Advisory leases + `Status.gpu_ids` | `/tmp/zndx-gpu-leases` + protocol |

Hard rules (unchanged):

- **No Marquez database** and no stock Marquez API as a second catalog.
- **No Python OL facade** beside Atlas.
- **DST method** stays in Atelier (and related labs); Signals stores **outcomes**
  (classifications, optional belief facets on runs) for governance and audit.
- Protocol evolution is **additive within a version**; breaking changes → `v2`.

## Submodule

```bash
# already pinned
git submodule update --init components/signals-protocol

# bump when protocol trunk advances
git -C components/signals-protocol fetch origin
git -C components/signals-protocol checkout origin/trunk
# commit pin in signals
```

| Path | Role |
|------|------|
| `components/signals-protocol/proto/` | Source of truth for protos |
| `components/signals-protocol/specification/` | Human specs per package |
| Generated stubs | Vendored **per adopter** (engines); Signals may generate for discovery services |

## Discovery (Atlas, Ranger, lineage)

Federated and external engines must **find** centralized services without
hardcoding lab topology. Today `Status` describes *engine* endpoints only.
The protocol core extends discovery so a peer learns:

| Service kind | What is advertised | Typical base |
|--------------|--------------------|--------------|
| `LINEAGE_OL` | OpenLineage ingest + Marquez-compat read | `http(s)://…:21010/api/v1` |
| `ATLAS_GOVERNANCE` | Atlas REST v2 (entities, types, classifications) | `http(s)://…:21010/api/atlas` |
| `RANGER_AUTHZ` | Ranger admin / policy evaluate | `http(s)://…:6080` (lab) |
| `MARQUEZ_UI` | Optional human UI (not SoR) | `http(s)://…:3000` |
| `ENGINE` | Peer `zndx.engine.v1` gRPC | `host:port` |
| `OIP` | Open Inference Protocol HTTP/gRPC | KServe-compatible base |

Discovery is **informative + capability-scoped**: advertising a URL does not
grant access. Edge (CF Zero Trust / IdP), Kerberos (data plane), and Ranger
policies still authorize. See [Identity and access](./identity-and-access.md).

Proposed protocol package (lands in `signals-protocol` first):
`zndx.discovery.v1` — `Discover` RPC and/or additive `StatusResponse.services[]`
fields listing `{ kind, base_url, auth_hint, healthy, version }`. Prefer
**additive fields on `Status`** for a minimal v1 step; split package if the
surface grows.

Engines **converge** by:

1. Calling discovery (or reading a Signals-published service map).
2. Emitting OpenLineage to `LINEAGE_OL` (not a local Marquez).
3. Registering / classifying assets via `ATLAS_GOVERNANCE` (or Signals hooks).
4. Evaluating access via `RANGER_AUTHZ` (or plugins that pull Atlas tags).

## External engines (Metabase and peers)

Metabase (AGPL) and similar BI/agent tools are **first-class external
participants**, not second SoRs:

| They may | They must not |
|----------|----------------|
| Read catalog/lineage via discovered APIs / FDW | Own a parallel lineage DB as product truth |
| Honor Ranger / edge authn for queries | Bypass ZT + Kerberos/data-plane identity |
| Appear as OL Jobs/Runs when they materialize datasets | Replace Atlas entity identity |

Signals may ship thin adapters (e.g. Metabase → dataset namespace mapping) under
ops docs; the **contract** remains discovery + OL + Atlas/Ranger.

## KServe Open Inference Protocol (OIP)

`signals-protocol` already patterns after OIP and maps `Complete`/`Status` as a
horizon peer. Multi-agent model ops make that horizon **active**:

| Need | Why OIP + signals-protocol together |
|------|-------------------------------------|
| Heterogeneous serving | Triton/KServe/external clusters speak OIP; zndx engines speak `Complete` |
| **Authorization** | Model invoke is a privileged action — identity + Ranger/tag context on the request path |
| **Provenance** | Every multi-agent inference should leave an OpenLineage Run (and optional reasoning retention) |

Direction:

1. **Map** `zndx.engine.v1.Complete` ↔ OIP `ModelInfer` (text/tensor payloads) in
   the protocol spec (expand existing OIP mapping table).
2. **Carry authz context** on federation/OIP calls (caller principal, optional
   Atlas entity / classification scope) — additive proto fields; enforcement at
   the serving edge and Ranger.
3. **Emit provenance** — engines (or a Signals sidecar) POST RunEvents to
   `/api/v1/lineage` for model ops: inputs (prompt hashes / dataset refs),
   outputs, model id from `CompleteResponse.model`, capability name.
4. **Optional OIP gateway** in Signals or Gaius that dual-registers
   `zndx.engine.v1` and OIP for the same capability set.

OIP is not a second governance plane. Atlas/Ranger remain law; OIP is the
**model invoke** lingua franca; OL is the **audit thread**.

## Relationship to Marquez

| Piece | Role |
|-------|------|
| Marquez-web | Default-stack UI for OL; proxy to Atlas `/api/v1` |
| Marquez API contract tests | Freeze the subset Signals implements |
| Stock Marquez server + Flyway | **Rejected** |

See [OpenLineage + Atlas](./openlineage-atlas.md).

## Phased delivery (protocol core)

| Phase | Deliverable |
|-------|-------------|
| **P0** | `components/signals-protocol` submodule + this doctrine |
| **P1** | Discovery: advertise Atlas + OL + Ranger on federation Status (or `discovery.v1`) |
| **P2** | Identity map: OL dataset ↔ `rdbms_*` qualifiedName; dual-path smoke |
| **P3** | Producer contract suite (polyglot, Gaius, Flink) → single `/api/v1` |
| **P4** | OIP mapping + authz/provenance fields in protocol; model-op RunEvents |
| **P5** | External peer pack: Metabase (and similar) discovery + lineage participation |
| **P6** | Kudu/FDW scale for OL/governance projections; Gaius/Aegir drop private facades |
| **P7** | Hermes: Weathership **memory provider** + **context engine** plugins; path to official listing |

## Hermes / Weathership memory

Hermes discovers memory providers under `plugins/memory/<name>/` and context
engines under `plugins/context_engine/<name>/` ([plugin system](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins)).
Only one external memory provider is active at a time
(`memory.provider` in config), additive to built-in MEMORY.md / USER.md
([memory providers](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory-providers)).

**Weathership** (Signals-backed) should:

1. Implement `MemoryProvider` with prefetch, turn sync, session extract, and
   agent tools (search/store) — backed by Signals AGE/OL (and optional belief
   facets), not a greenfield DB.
2. Implement a **context engine** that compacts with lineage-aware retention
   (pre-compression extract into Weathership memory, similar spirit to
   ByteRover’s pre-compression extraction).
3. Use federation **discovery** for Atlas/Ranger/OL bases; emit OpenLineage for
   memory writes and model ops (authz + provenance).
4. Ship as installable Hermes plugins; eventually qualify as an **official**
   reasoning-enabled memory service provider in the Hermes ecosystem.
5. Keep **superset** capabilities fleet-side (and exposable as tools/skills):
   mechanistic interpretability (SAE/CLT), topological structure (PH,
   Ollivier–Ricci), multi-engine `Complete`/`Remediate`—without waiting for
   Hermes core to absorb them. Deeper core integration remains open later;
   plugins-first is the **current** strategy.

Submodule: [`components/hermes-agent`](../components/hermes-agent.md).

## Related

- Submodule: `components/signals-protocol`
- Submodule: `components/hermes-agent`
- [OpenLineage + Atlas](./openlineage-atlas.md)
- [Identity and access](./identity-and-access.md)
- [Atlas → Kudu outbox](./atlas-kudu-outbox.md)
- Protocol README (federation face, OIP horizon, co-tenancy)
- Gaius: CO-TENANCY draft; `hx.lineage`; FEDERATION.md
- Aegir: polyglot OpenLineage; former `gateway/marquez.py` (shape reference only)
- Atelier: DST / classification method lab
