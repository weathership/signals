# Queues lineup: archive / current / scratch × YuniKorn resource management

**Date:** 2026-08-13  
**Status:** design research (no implementation this note)

## Confirmed: Aegir projection lives under `build/dev/`

Package `aegir.lineup` materializes Data Products into a **gitignored KB projection**:

```text
aegir/build/dev/
  index.json                 # gateway listing (id → root, relpath, links)
  path_manifest.json
  current/                   # regenerable on each `python -m aegir.lineup build`
    lens/ lexicon/ ontology/ relational/ content/ …
  scratch/                   # preserved; unreleased / in-progress work
  archive/                   # preserved freezes (e.g. 2026Q2/, 2026Q3/)
```

- **Build:** `just kb-build` → `python -m aegir.lineup build`  
  (`current/` cleared and rebuilt; `scratch/` + `archive/` kept.)
- **Serve:** gateway `/api/kb/index`, `/api/kb/note/{id}?root=…` reads `build/dev` only.  
  React lineup does **not** own the artifacts — it presents the projection.
- **Roots in UI:** side-nav SECTION = `archive | current | scratch` (Lineup.tsx `ROOTS`).

Live index counts (lab): ~current 13k · scratch 73k · archive 19k notes.

## Yk-web UX (queues) — inspect, not edit

Upstream SPA (`rch-yunikorn-web`):

| Surface | Role |
|---------|------|
| `/queues` queue-rack | Hierarchical browse + heat bars |
| Drawer “Queue Info” | Name, status, allocated/pending/max/guaranteed, abs used, apps |
| `/queues-v2` | Topology viz |

**No save/edit/update controls** in queues-view — operational **read/inspect** of the live scheduler. Resource management is **config**, not UI mutation in stock yk-web.

## YuniKorn API (read + validate + deploy path)

| Endpoint | Method | Role |
|----------|--------|------|
| `/ws/v1/partition/{p}/queues` | GET | Live tree + **runtime** usage (allocated pods, abs used, …) |
| `/ws/v1/partition/{p}/queue/{q}` | GET | Single queue |
| `/ws/v1/config` | GET | **Declared** scheduler config (YAML body; queues.yaml content) |
| `/ws/v1/validate-conf` | POST | Validate a candidate config (no apply) |
| Config apply | **not** REST PUT in this build | Lab/RKE2: ConfigMap / Helm (`yunikornDefaults.queues.yaml`, optional `yunikorn-configs`) |

SoR split:

- **Runtime truth (what’s running):** REST queues + live allocations.  
- **Declared policy (what *should* run):** `queues.yaml` in ConfigMap / zarf values / git.  
- **Validate before promote:** `POST /ws/v1/validate-conf`.

## Paradigm map: lineup roots → queue resource management

| Root | Aegir meaning | Queues / K8s meaning |
|------|---------------|----------------------|
| **current** | Projection of released / authority substrate; default trailhead | **Active** queue config **and** live allocation view — what is controlling scheduling **now** |
| **scratch** | Unreleased work; edit without clobbering current | **Working copy** of `queues.yaml` (+ notes): edit, review, validate; **pending promote** to current / cluster |
| **archive** | Named freezes of past projections | **Snapshots** of past applied configs (and optional frozen live digests) for audit / rollback compare |

### Promote path (Aegir-shaped)

```text
scratch (edit artifacts under build/dev/scratch/…)
    → validate-conf (POST)
    → promote → current projection + apply to cluster (ConfigMap / GitOps)
    → optional archive freeze of previous current
live GET /ws/v1/partition/.../queues  always reflects cluster after apply
```

UI:

- Side-nav SECTION = root (same control as Aegir).  
- **current** trail: mostly **read** panels (Queue Info from live REST + declared config overlay).  
- **scratch** trail: editable notes / structured queue documents; actions Validate / Diff vs current / Promote.  
- **archive**: open freeze, diff vs current, optional restore-to-scratch.

## Projection layout proposal (signals)

Mirror Aegir under signals (not yk binary):

```text
signals/build/dev/          # or SIGNALS_YK_KB_DIR
  index.json
  current/
    queues/
      partition-default.md          # summary note
      root.md
      root.signals.md
      …
    config/
      queues.yaml                   # declared policy (mirrors /ws/v1/config shape)
  scratch/
    queues/ …
    config/queues.yaml              # WIP
  archive/
    2026-08-13T…/                   # freeze key
      config/queues.yaml
      queues/ …
```

`python -m signals.queues build` (name TBD) would:

1. Pull live tree + `/ws/v1/config` into **current** notes (regenerable).  
2. Leave **scratch** edits intact.  
3. On promote: copy scratch→current artifacts, apply ConfigMap, optional archive stamp.

Gateway/API for lineup shell: same shape as Aegir (`/api/kb/index`, `/api/kb/note/…`) or signals-ui native routes.

## Lineup UX (recap — not what we built)

Aegir: **side-nav seeds + full-height horizontal panel trail + note body + optional HoloViews**.  
Queues rewrite must use that shell; **current/scratch/archive** is the side-nav SECTION, not a toolbar tab.

Live YK data fills **current** panels’ “runtime” section; declared YAML fills “policy” section. Scratch panels prefer policy docs; runtime may be “preview if promoted” or omitted until validate.

## Non-goals (stock yk-web)

- Do not depend on Angular yk-web for edit.  
- Do not treat GET `/ws/v1/partition/.../queues` alone as the editable artifact (usage ≠ policy).

## Next implementation steps (when greenlit)

1. Design doc in `docs/current` (queues lineup + roots + promote).  
2. Scaffold `build/dev/{current,scratch,archive}` + projector from live config/queues.  
3. Client lineup island with SECTION root + trail (no HoloViews required for v1).  
4. Wire validate-conf + GitOps/ConfigMap promote.
