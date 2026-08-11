# Queues feature: yk-web space × Cloudflare/Kumo flow layout

**Date:** 2026-08-11  
**Goal:** Iterate signals-ui `/queues` toward yk-web capability (core YuniKorn surface)
while using a Cloudflare Dashboard–style **flow layout** under **Keiretsu/Kumo** chrome
(reference: `build/cloudflare-ui.png`).

## 1. yk-web queues feature space

Reference: `~/local/src/asf/rch-yunikorn-web/`

### Routes

| Path | Component | Role |
|------|-----------|------|
| `/queues` | `QueuesViewComponent` + `QueueRackComponent` | **Primary** operator surface |
| `/queues-v2` | `QueueV2Component` | Graph visualization (D3 flextree) |

### API contract (SchedulerService)

```
GET /ws/v1/partitions
GET /ws/v1/partition/{partition}/queues          → tree (root + children[])
GET /ws/v1/partition/{partition}/queue/{q}/applications  → leaf drill-down
```

Mapping in `scheduler.service.ts` builds `QueueInfo`:

| Model field | REST / derived |
|-------------|----------------|
| `queueName`, `status`, `isLeaf`, `isManaged`, `partitionName` | direct |
| `children[]` | recursive `generateQueuesTree` |
| `maxResource`, `guaranteedResource`, `allocatedResource`, `pendingResource` | resource formatters |
| `absoluteUsedCapacity`, `absoluteUsedPercent` | capacity math for heat color |
| `properties[]`, `template` | config dump |
| `MaxRunningApps`, `RunningApps` | app counts |
| UI state: `isExpanded`, `isSelected` | client-only |

### Layout A — `/queues` “rack” (core capability UI)

**Mental model:** horizontal **levels** of the queue tree, not a flat table.

1. **Partition selector** (persisted preference).
2. **Queue racks** — one column per depth (`level_00` …), each a vertical stack of cards.
3. **Card (queue-rack item):**
   - Name header (leaf vs expand +/-)
   - **Progress bar** = `absoluteUsedPercent`
   - **Heat color** on header: white → green (>60) → amber (>75) → red (≥90)
4. **Expand** loads children into the **next** column; collapsing closes deeper columns.
5. **Selection** opens an end **drawer** (Queue Info):
   - Name, status, allocated / pending / max / guaranteed
   - Absolute used capacity
   - Max / running apps
   - Arbitrary `properties`
   - If leaf → **link to applications** for partition+queue

This is hierarchical **browse + inspect + navigate to apps** — the operational core of YK multi-tenancy.

### Layout B — `/queues-v2` graph

- D3 + **flextree** cards (300×120), pan/zoom, rotate H/V, fit-to-screen
- Card zones: top (name), middle (body), bottom (status strip)
- Click toggles **detail side panel** (same resource fields as drawer)
- Expand/collapse children via hover “+”

Good for topology overview; heavier and less keyboard/table friendly. signals-ui should treat this as **optional viz**, not the only path.

## 2. Cloudflare UI reference (`build/cloudflare-ui.png`)

Workers & Pages **Overview** for `weathership-web` — dense but scannable **dark flow layout**:

| Region | Pattern | Why it works for queues |
|--------|---------|-------------------------|
| **Top chrome** | Product tabs + entity title | Partition + “Queues” context |
| **Center flow band** | Left inputs → **center selected node** → right outputs | Ancestors/siblings → **selected queue** → apps/bindings/properties |
| **Cards as nodes** | Rounded elevated cards, chevrons, **count badges** | Queue cards with child count / RunningApps |
| **Edges** | Subtle connectors into the focus node | Parent→child hierarchy without full D3 |
| **Detail in node** | Nested rows (Observability toggles, Bindings list) | Resources + properties without leaving canvas |
| **Below fold** | Metrics strip (sparklines) + list cards | Capacity time-series later; app list / versions |
| **Side/secondary** | Domains & routes, next steps | Partition summary, placement rules, next actions |

**Kumo / Keiretsu alignment:** recessed canvas, elevated cards, strong chrome, monochrome + one accent — already our `theme-keiretsu.css` / Atelier chrome. We do **not** copy Cloudflare brand; we copy **spatial grammar**: flow of relationships, focus node, supporting metrics.

## 3. Gap: signals-ui today

`/queues` is a **flat table** + raw JSON:

- ✓ Partition select, flatten tree names, leaf → apps link  
- ✗ No level racks / expand columns  
- ✗ No capacity heat or progress  
- ✗ No select-to-inspect drawer/panel  
- ✗ No properties / pending / absolute used  
- ✗ No topology (flow or tree graph)  
- ✗ Raw JSON dumps dominate the page (debug, not ops)

## 4. Target layout for signals-ui `/queues` (iteration)

### Phase Q1 — “Kumo flow rack” (HTML/CSS, no D3 required)

```
┌─ Partition [default ▾] ─────────────────────────────────────────┐
│                                                                  │
│  ┌ Flow canvas (elevated card) ───────────────────────────────┐  │
│  │  [root ●]──┬──[signals 0 apps]                             │  │
│  │            ├──[hermes]                                     │  │
│  │            ├──[default] ← selected                         │  │
│  │            ├──[aegir]                                      │  │
│  │            └──[atelier / gaius …]                          │  │
│  │                 │                                          │  │
│  │                 ▼                                          │  │
│  │            ┌ selected queue card ────────────────────┐     │  │
│  │            │ root.default · Active · leaf            │     │  │
│  │            │ used ████░░ 12%   max …  guar …         │     │  │
│  │            │ RunningApps n · properties…             │     │  │
│  │            │ [Open applications →]                   │     │  │
│  │            └─────────────────────────────────────────┘     │  │
│  └────────────────────────────────────────────────────────────┘  │
│  ┌ Metrics (optional strip) ─┐  ┌ Apps on queue (if leaf) ────┐  │
│  │ headroom / allocated      │  │ table or empty state        │  │
│  └───────────────────────────┘  └─────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

**Mapping CF → YK:**

| CF | signals-ui queues |
|----|-------------------|
| Domains / Workers / Queues sources | Depth-0..n queue **racks** or compact tree rail |
| Center worker card | **Selected queue** focus card |
| Bindings panel | Leaf **applications** + property list |
| Metrics 24h | Headroom / allocated / absolute used (static first; history later) |
| Domains & routes | Partition list + placement-rule summary (later) |

Implementation fit for Rust/Askama:

- Server renders full tree once from REST (already have `flatten_queues` + children).
- **Progressive disclosure:** selected queue id in query `?partition=&queue=`.
- CSS grid/flex for horizontal racks; SVG or pure CSS connectors for 1–2 levels (our federation tree is shallow: `root` → leaves).
- Capacity heat = same thresholds as yk-web rack (`absoluteUsedPercent`).
- Collapse raw JSON behind `<details>` or remove from primary path.

### Phase Q2 — optional topology viz

- Client-side or server-rendered SVG tree **or** progressive enhancement with a small canvas.
- Avoid shipping D3 in the binary if possible; prefer CSS flow for federation depth.
- queues-v2 parity only if operators need deep multi-level trees.

### Phase Q3 — manage (beyond yk-web read-only)

yk-web is largely **read/inspect**. True “manage” (create queue, set ACL, quotas) is config/API write — out of scope until YK admin APIs are productized. For now **inspect + navigate + capacity** is the bar.

## 5. Data completeness checklist (vs QueueInfo)

| Field | signals-ui now | Q1 target |
|-------|----------------|-----------|
| Tree children | partial (flatten) | full tree + expand |
| allocated / max / guaranteed | table strings | focus card + heat |
| pending | no | yes |
| absoluteUsed % | no | progress + color |
| properties | no | detail panel |
| RunningApps / MaxRunningApps | no | badge on card |
| apps link | leaf only | focus CTA |
| partition switch | yes | keep + remember |

## 6. Recommended next implementation slice

1. Restructure `/queues` template into **flow canvas + focus card + side/detail** (Keiretsu cards).  
2. Enrich parser: `pendingResource`, absolute used %, properties, app counts.  
3. Selection via `?queue=` query (shareable, no JS required for core path).  
4. Optional light JS only for expand/collapse animation if needed.  
5. Keep `/api/yk/ws/v1/partition/{p}/queues` as machine API; UI stops dumping full JSON by default.

## 7. Non-goals for first iteration

- Full D3 flextree parity with queues-v2  
- Cloudflare left nav / product shell clone  
- Queue mutation (create/delete)  
- Historical capacity sparklines (needs metrics series)

## 8. Sitemap: Nodes folded under Queues (2026-08-11)

Top-level **Nodes** removed from chrome to free prime nav real estate.
YK nodes remain first-class capability:

| Path | Role |
|------|------|
| `/queues` | Primary — queue tree + **partition nodes strip** |
| `/queues?panel=nodes` | Full nodes table for partition |
| `/nodes` | **307/302 temporary redirect** → `/queues?panel=nodes` |

Rationale: queues + nodes are the same partition-scoped YK control surface
(yk-web had both top-level; we collapse under Queues like CF folds related
bindings into the worker overview). Applications stay top-level (cross-queue
workload list). Dashboard partition links use `panel=nodes`.

## 6b. Landed (Kumo flow build)

Shipped in signals-ui:

- `templates/queues.html` — flow canvas + focus + nodes strip / panel
- `assets/css/shell.css` — `.kumo-flow`, `.queue-card`, heat, focus
- `main.rs` — `build_queue_levels` / `QueueCard` parser
- Selection: `/queues?partition=default&queue=root.signals`
- Smoke: HTTP 200, focus + Open applications for leaves, nodes 307 redirect
