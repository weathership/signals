# Signals protocol core

Signals is the **system of record** and the **central discovery surface** for the
zndx federation: lineage, governance metadata, and authz decision inputs live
here. **Core** federated engines (Gaius, Ægir, Atelier, and future in-family
projects such as synth or vigil) and **license-external** peers (e.g. Metabase)
operate on the fleet; they **discover and call** centralized services instead of
each growing a private catalog, lineage store, or policy engine.
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

## How the federation contract evolves

**signals-protocol is the shared federation contract** (engine-to-engine wire,
capability semantics, co-tenancy conventions, OIP mapping). It is still early:
much of the foundational work for a durable multi-engine contract remains
ahead of us.

That work is **organic, not top-down**. Requirements surface when a peer engine
needs something the wire does not yet express — the first live cross-engine
call exposed package-scoped service paths (`UNIMPLEMENTED` despite matching
messages), which is why `zndx.engine.v1.Engine` sits **beside** each project’s
native service. Later needs (structured `Complete`, boundary `Remediate`,
Status fields for GPU leases, OIP tensor conventions) follow the same pattern:
implement enough in the engine to ship product value, then **promote** stable
shapes into the protocol so every peer can speak them.

**Core peer engines** (Gaius, Ægir, Atelier, and planned siblings such as synth
or vigil) form one architectural family: multi-service gRPC, capability-not-model,
private vLLM (or equivalent), lattice ports, and co-tenancy leases. That family
grew in those codebases as product work demanded it; protocol requirements
continue to surface there first.

**License-external peers** (Metabase today) are different by **requirement**,
not preference. AGPL (and similar) cannot be combined into ASL2 Signals or core
peer distributions, so their engines must live in an **isolated** tree: process
boundary + protocol wire only. mbengine is a real federation participant
(`Status` / lattice unit) but it is **not** a core Signals engine project and
is not expected to share the Gaius-lineage engine stack. See
[Core vs license-external engines](#core-vs-license-external-engines).

Signals **hosts** the platform (governance SoR, critical plane, process group
control) and **pins** the protocol submodule. When attachment work (peer units,
lattice-ci, Metaflow/CE) meets a gap, prefer extending **signals-protocol**
(or documenting an explicit interim) over forking per-project wire dialects.

| Layer | Maturity (honest) | Where it lives |
|-------|-------------------|----------------|
| Native product gRPC | Mature in each **core** peer | Gaius / Ægir / Atelier / … trees |
| Multi-service + capability engines | In production use; still converging | **Core** peer `engine/` packages |
| `zndx.engine.v1` shared service | **v1 landed; incomplete relative to real peer needs** | `signals-protocol` + per-peer bindings |
| OIP dual-registration / mapping | Partial (stronger in some engines than others) | Protocol spec + peer OIP servicers |
| License-external engines | Isolated adapters (e.g. mbengine) | Separate trees (e.g. AGPL Metabase) |
| Platform process attachment | Lab-usable (ready gate, units, lattice-ci) | This repo (`peer-contract`, systemd) |
| Cross-engine product flows | Early (CE map, Remediate, federated Complete) | Protocol + peers together |

**Working stance:** treat protocol growth as co-evolution with peer engines —
especially **core** peers, where shared engine practice is densest —
requirements materialize in real projects; the contract absorbs what should be
shared. Expect substantial further foundation work on signals-protocol itself
before “federation complete” is a fair claim.

### Signals as hub — early on the engine axis, not “thin forever”

Gaius, Ægir, and Atelier already carry substantial capability-engine
implementations (multi-service gRPC, vLLM managers, co-tenancy, Remediate,
product services). Signals is **early** on that same axis: federation
architecture (protocol, peer units, lattice gates, group lifecycle) is still
being nailed down, so this tree has not yet grown a large engine surface — not
because engine work is forbidden here, but because it is **too early** to have
implemented much of it *yet*.

What is already useful to centralize (and what accelerates the initiative
while the architecture settles):

| Hub control (today) | Role |
|---------------------|------|
| Critical plane + `signals-ready` | One foundation readiness gate |
| `signals.target` + peer units | One group lifecycle for co-tenant engines |
| `peer-contract` + lattice-ci | One accept surface (codegen Status + reflection) |
| Platform Metaflow / Airflow / Eventing / YK / Atlas | Shared production path without re-hosting |
| `signals-protocol` pin | One wire contract to promote peer-proven shapes into |

**Working mode while early:** drive from hub control and protocol gaps; land
proven depth in peers that already have engines (and promote stable shapes into
signals-protocol). Peer sessions stay product-local; convergence is measured
here (`lattice-ci`, unit graph, protocol bumps). Engine functionality in
Signals itself can grow when the federated architecture is solid enough to
host it honestly — maturity, not a permanent “thin product” identity.

### Doctrine: total commitment as a federation peer

Adopting **signals-protocol** as a federation peer is **total commitment**, not
a decorative Status endpoint on a half-running stack. That applies whether the
peer is a mature product engine (Gaius today) or a younger tree: peerhood means
full capacity **as that project defines it**, honest ops, and remediation —
not a lattice-only shell built only to pass accept.

| Obligation | Meaning |
|------------|---------|
| **Full project stack** | Under `signals.target`, unit start brings the peer’s **full devenv stack** as that project defines production-local operation (`just up` / `devenv up`): capability engine **and** product UI/gateway/DB/supporting processes — not an engine-only or Status-only subset. |
| **Full engine capacity** | The peer runs its **real** capability engine (product multi-service gRPC, models, co-tenancy, native surfaces as designed for that project) — not a quasi-engine or Status-only process. |
| **Honest operational state** | `start` / `stop` / `restart` (unit and group) must take the **full stack** through real transitions: processes up with intended capacity, ports freed and workers down on stop, restart = full stop then full start. Partial “already READY — skip” or orphan listeners that survive stop are **error conditions**, not success modes. |
| **Remediation on failure** | When capacity or a transition fails, that is a fault requiring remediation (peer-local health/FMEA/fix paths — e.g. Gaius `/health fix engine` and related recovery). Optimistic Status that advertises healthy capabilities while backends are down is not accept. |
| **Hub vs peer (while architecture is early)** | Peers own full-stack depth and lifecycle honesty for their lattice + product ports. Signals currently owns group control, contract, and lattice-ci; it does not yet re-home peer engines into this tree. That is sequencing, not a ban on future Signals engine work. |

**Anti-patterns (not federation):**

- Engine-only unit start that leaves product UI/gateway dark while claiming peer ready
- Synthetic always-healthy Status rows so lattice-ci passes without resident capacity
- Unit start that no-ops because an orphan still answers Status
- Unit stop that leaves lattice ports, UIs, or engine process groups alive
- Interactive `devenv up` stacks fighting the systemd unit for the same lattice port
- Treating “Signals is thin/early” as doctrine that excuses half-committed peers or freezes engine growth here forever

**Accept implication:** `lattice-ci` / `Engine/Status` are necessary gates, not a
substitute for full capacity. Peer-unit accept should include clean
start/stop/restart of *this* peer’s engine under `signals.target` (single
listener ownership, honest health). Detail: [Peer unit acceptance
spec](../operations/peer-unit-spec.md) and [Peer integration](../operations/peer-integration.md).

### Platform capability: Scheduler (`zndx.scheduler.v1`)

Signals’ first thick engine capability is **federated scheduling**
(`capability=scheduler`; lab `model=yunikorn`, later PBS/SLURM).
Thin clients call `zndx.scheduler.v1.Scheduler` on the Signals lattice
(`:50551`); the engine privately talks to the backend and owns
archive/current/scratch projection. See
[YuniKorn queue management](./yunikorn-queue-management.md) (lab adapter).

### Spec vs tooling surfaces

| Layer | Role |
|-------|------|
| **`.proto` + gRPC services** | The specification (OIP-aligned). Codegen is how we **implement** clients and servers. |
| **Generated stubs** | First-party path for lattice-ci, unit probes, peer libraries (`scripts/zndx_engine_status.py`, peer `engine/generated/`, …). |
| **gRPC server reflection** | Install requirement so **external** tools can use bare `grpcurl host:port Method` without cloning our tree. |

Reflection is not a substitute for the proto. First-party scripts should not
prefer “raw grpcurl -proto” as a substitute for codegen — they should call
generated clients from `signals-protocol`.

| Requirement | Why |
|-------------|-----|
| **Codegen from `proto/`** | Proper protocol implementation for engines and our automation |
| **Server reflection on lattice ports** | External/operator grpcurl without extra steps |

Python engines: `grpcio-reflection` + enable at server start. Lattice-ci runs
**both** a generated Status client and a reflection check.

### Language: brass-tacks naming

Name platform, wire, and **foundational theory** by the terms a practitioner
(or inventor) already uses — not by product metaphor, softened ops slang, or
in-house glosses that drift from the definition.

**Two tests** (fail either → rename until both pass, then document once):

1. **Systems:** Can someone who only knows the underlying tech (gRPC, systemd,
   CI) map the phrase to a concrete artifact — port, unit, service registration,
   gate — without a project glossary?
2. **Theory:** Would the people who invented (or standardly formalized) the
   concept recognize our names, types, and invariants as *their* object — not a
   vague cousin? Example: persistent homology should read cleanly to Gunnar
   Carlsson (or any TDA practitioner): Vietoris–Rips filtration, homology
   dimension, birth/death pairs, essential classes (`death = +∞`), not
   rebranded “shape scores.” Same bar for Dempster–Shafer (Bel/Pl/K), SAGE,
   TreeSHAP, Ollivier–Ricci, and future topology / belief / geometry work.

| Prefer | Avoid | Why |
|--------|-------|-----|
| **multi-service gRPC** | multi-face gRPC | One listen port, several services on one server — gRPC’s own model |
| **lattice-ci** / `*-ci` | smoke (for elevated gates) | Repeatable accept gates are CI; smoke is one-off first-run feedback |
| **protocol / codegen path** | proto fallback | `.proto` is the specification, not a backup |
| **peer-scoped stop** | soft stop | Full unit stop, scoped to one peer — not a partial or vague halt |
| **Domain terms + faithful APIs** | Metaphor wrappers for math | Implementations stay inspectable against papers and reference libraries (e.g. Ripser `dgms`) |

Product metaphors are fine in UI copy when they map 1:1 to a brass-tacks term
documented here. Do not invent a second vocabulary for the same process shape
or the same mathematical object.

## Layers

```text
  UIs / external engines          Federated engines (OIP + zndx.engine.v1)
  ┌──────────────┐                ┌─────────┬──────────┬─────────┐
  │ Marquez-web  │                │  Aegir  │ Atelier  │  Gaius  │
  │ Metabase*    │                │ :50151  │ :50251   │ :50051  │
  │ Atlas UI     │                └────┬────┴────┬─────┴────┬────┘
  └──────┬───────┘                     │         │          │
         │  HTTP                       │  multi-service gRPC
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

  * AGPL Metabase is a *license-external* peer (isolated engine, not core family):
    process + wire only; consumes catalog/lineage/authz; never SoR or vendored.
```

## Core vs license-external engines

Two kinds of “peer” attach to Signals. Conflating them muddies protocol work and
peer-unit sessions.

| | **Core federated engines** | **License-external peers** |
|--|----------------------------|----------------------------|
| Examples | Gaius, Ægir, Atelier; future **synth**, **vigil**, … | **Metabase** (AGPL) today |
| Why separate trees | Product modularity; shared ASL2 (or compatible) line | **License incompatibility** (AGPL ↛ ASL2 combine) |
| Engine architecture | Shared **family** (capability engines, multi-service gRPC, co-tenancy) | **Isolated** product engine (e.g. mbengine); not Gaius-lineage |
| Protocol role | Primary source of organic `signals-protocol` requirements | Speaks enough wire to join; not the design center for core engine law |
| Platform attach | `signals.target`, lattice ports, Metaflow/CE/YK as applicable | Same *process* pattern optional; no source/jar into Signals or core peers |
| SoR | Never — Atlas/lineage/authz stay on Signals | Never — same |

Metabase is external **by requirement**: introducing an engine there is
inherently isolated so the product can federate without licensing contamination.
Architecturally it is distinct from Gaius / Ægir / Atelier and from any future
**core** Signals projects. Operator install and dual-map still matter; they do
not make Metabase “another Atelier.”

| Concern | Authority | Client surface |
|---------|-----------|----------------|
| Governance types & classifications | **Atlas** on `signals` PG + AGE | `/api/atlas/*` |
| Runtime lineage (Job/Run/Dataset) | **Same Atlas process** + `signals_ol` | `/api/v1/*` (OpenLineage + Marquez-compat) |
| Authorization decisions | **Ranger** (Atlas tags as input) | Ranger REST / plugins; policy evaluate via discovery |
| Human OL UI | **Marquez-web** | `:21011` (Atlas HTTP + 1) → proxies `/api/v1` only |
| Agent memory + compaction | **Weathership** plugins on Hermes | `MemoryProvider` + context engine ([plugins](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins)) |
| Engine-to-engine inference | **`zndx.engine.v1`** | `Complete` / `Status` / `Remediate` |
| Heterogeneous model serving | **KServe OIP** + signals-protocol mapping | `ModelInfer` / readiness; authz + provenance on the wire |
| GPU co-tenancy | YK Application claim (`federation.zndx.org/gpu`) + `Status.gpu_ids` | Queue occupancy SoR; `/tmp/zndx-gpu-leases` is intra-node refuse only |

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
| `MARQUEZ_UI` | Optional human UI (not SoR) | `http(s)://…:21011` (Atlas HTTP + 1) |
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

Metabase (AGPL) and similar BI/agent tools are **license-external**
participants — **architecturally isolated** from the core engine family (see
[above](#core-vs-license-external-engines)). They are first-class on the
**wire and process group**, not second SoRs and not core engine projects:

| They may | They must not |
|----------|----------------|
| Read catalog/lineage via discovered APIs / FDW | Own a parallel lineage DB as product truth |
| Honor Ranger / edge authn for queries | Bypass ZT + Kerberos/data-plane identity |
| Appear as OL Jobs/Runs when they materialize datasets | Replace Atlas entity identity |

Signals may ship thin adapters (e.g. Metabase → dataset namespace mapping) under
ops docs; the **contract** remains discovery + OL + Atlas/Ranger.

Optional install (separate AGPL checkout + `metabase.service` under
`signals.target`, never vendored into this tree):
[Peer integration — Metabase](../operations/peer-integration.md#external-engines-metabase-agpl).

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
| **P0b** | Governance scale plane: Atlas/Ranger **Kudu projections** + **RustFS** on RAID — required so multi-engine devenv does not crush Postgres/AGE ([governance-scale-plane](./governance-scale-plane.md)) |
| **P1** | Discovery: advertise Atlas + OL + Ranger + `OBJECT_STORE` on federation Status (or `discovery.v1`) |
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
