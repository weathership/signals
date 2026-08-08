# Signals protocol core — direction lock

**Date:** 2026-08-08

## Confirmed

- Treat **Signals** as protocol core + SoR (lineage, governance, authz inputs).
- **Marquez-web** = UI lens only; no Marquez DB.
- **Federated engines** (Aegir, Atelier, Gaius) = operating surface.
- **External** engines (e.g. AGPL **Metabase**) participate via discovery + APIs; not SoR.
- Submodule: `git@github.com:zndx/signals-protocol.git` → `components/signals-protocol` (`trunk`).
- **Augment protocol** for discovery of **Atlas** and **Ranger** so engines converge on
  centralized lineage and auth/authz.
- **KServe OIP** integration with signals-protocol protos — authorizations + provenance
  critical for multi-agent model ops.
- DST method remains healthy in **Atelier**; Signals stores outcomes.

## Landed this pass

- [x] Submodule `components/signals-protocol`
- [x] Architecture: `docs/current/src/architecture/signals-protocol-core.md`
- [x] SUMMARY + components overview + OL doc cross-links

## Protocol PR targets (signals-protocol repo)

Additive proposals (exact field numbers TBD in PR):

### 1. Service discovery (Atlas / Ranger / OL)

Option A (minimal): extend `StatusResponse` with repeated `ServiceEndpoint`:

```protobuf
message ServiceEndpoint {
  string kind = 1;       // LINEAGE_OL | ATLAS_GOVERNANCE | RANGER_AUTHZ | MARQUEZ_UI | OIP | ENGINE
  string base_url = 2;   // scheme://host:port[/path]
  string auth_hint = 3;  // e.g. "zt-oidc" | "kerberos" | "none-lab"
  bool healthy = 4;
  string version = 5;
}

// StatusResponse additive:
// repeated ServiceEndpoint services = 4;
```

Option B: `zndx.discovery.v1.Discovery/Discover` if the surface outgrows Status.

**Publisher:** Signals (or a thin discovery sidecar next to Atlas) answers for
central services; engines continue to answer for their own `ENGINE` endpoints.

### 2. OIP + authz + provenance

- Spec table: `Complete` ↔ `ModelInfer`; `Status` ↔ `ServerMetadata`/`ModelReady`.
- Additive request metadata (names illustrative):

```protobuf
message AuthzContext {
  string principal = 1;           // caller identity (edge/JWT/Kerberos principal)
  string subject_entity = 2;      // optional Atlas guid / qualifiedName scope
  repeated string tags = 3;       // optional classification codes in scope
}

// CompleteRequest additive:
// AuthzContext authz = 7;
// string run_id = 8;             // correlate to OpenLineage Run
```

- Provenance: serving path emits OL RunEvent to discovered `LINEAGE_OL` with
  job namespace e.g. `engine.{project}`, inputs/outputs, `model` from response.

### 3. CO-TENANCY.md

Promote Gaius draft (`220057_cotenancy_participation_contract.md`) into
`signals-protocol` as `CO-TENANCY.md` (R1–R6).

## Engine / product homework

| Who | Work |
|-----|------|
| Signals | Publish discovery; keep `/api/v1` + Atlas + Ranger healthy; Marquez contract tests |
| Aegir | Emit OL to Signals; consume discovery; drop private Marquez facade over time |
| Atelier | Shared `zndx.engine.v1` face; classifications → Atlas; R2 co-tenancy |
| Gaius | Shared face + lease write (R1/R5/R6); hx.lineage → Signals OL |
| Metabase | External peer: catalog via FDW/APIs; lineage participation when materializing |

## Non-goals

- Marquez Flyway DB, Python OL facade, DST re-lab in Signals
- Replacing OIP with a private model API for external clusters
