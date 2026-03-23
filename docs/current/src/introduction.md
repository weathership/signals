# Signals 360

Signals 360 is a metadata governance platform that automatically classifies database columns against a BFO-grounded ontology using uncertainty-aware evidence fusion. The platform integrates Apache data infrastructure (Impala, Kudu, Iceberg, Atlas, Ranger) into an HMS-free query stack with automated classification and policy enforcement.

## Problem

Enterprise data platforms accumulate thousands of tables and columns with inconsistent naming, no sensitivity labels, and no formal governance metadata. Manual classification is expensive, error-prone, and immediately stale. Flat confidence scores from ML classifiers conflate "definitely Payment Card Number" with "definitely some kind of Payment Information but unsure which sub-type" — a distinction that matters for policy enforcement.

## Approach

The classification pipeline combines four independent evidence sources — embedding similarity, gradient-boosted prediction, regex pattern detection, and column name matching — through Dempster-Shafer belief functions rather than simple score averaging. Each source produces a mass function over a restricted frame of discernment derived from the taxonomy hierarchy. Dempster's rule of combination yields belief intervals \\([Bel(A), Pl(A)]\\) at every hierarchy level, exposing where evidence commits versus where it merely does not contradict.

The interval width \\(Pl(A) - Bel(A)\\) quantifies epistemic uncertainty. The Dempster conflict \\(K\\) between sources flags disagreement that flat scores suppress. Together, these diagnostics separate confident leaf-level classifications from cases that warrant human review — a property that point estimates cannot provide.

### Evidence Sources

| Source | Signal | Mass Function |
|--------|--------|---------------|
| **Cosine similarity** | Sentence-transformer embedding (MiniLM-L6, 384-dim) compared against taxonomy reference embeddings | Softmax over similarities, discounted to \\(\Theta\\) |
| **CatBoost prediction** | Gradient-boosted model trained on 992-dim feature vectors (dual embedding + 12 discrete features + cosine similarities) | `predict_proba()` mapped to singletons, variance-adaptive discounting when virtual ensembles are available |
| **Pattern detection** | 8 regex detectors (email, SSN, credit card, phone, UUID, IPv4, URL, ISO date) | High-confidence mass (0.9) on matched categories; vacuous when no patterns detected |
| **Name matching** | Column name matched against category labels via exact, abbreviation, and word-overlap tiers | Tiered mass assignment (0.7 / 0.5 / 0.3); vacuous on no match |

The frame of discernment uses a restricted focal set — singletons, internal taxonomy nodes, and empirically identified confusable pairs — reducing computational complexity from \\(2^{30}\\) to ~53 focal elements for the SIGDG taxonomy (30 leaves). Each Dempster combination requires \\(O(F^2)\\) operations over focal elements; with 4 sources and \\(F \approx 53\\), classification overhead is sub-millisecond per column.

### Cosine Reliability Regimes

Cross-benchmark analysis revealed that cosine similarity ranges from near-perfect (99.4% on semantically named columns) to destructive (1.6% on generic names, where it adds pure conflict to CatBoost's 81.6% accuracy). Three regimes emerge: high cosine confidence (>0.35) where cosine is reliable, low (<0.05) where CatBoost should dominate, and an intermediate regime where standard Dempster combination is appropriate. The current implementation uses fixed discounts; adaptive confidence-gated discounting is a planned refinement. See [Evidence Fusion](./architecture/evidence-fusion.md) for the regime analysis and [Combination Rule Choice & Limitations](./architecture/evidence-fusion.md#combination-rule-choice--limitations) for design trade-offs.

## Architecture

The platform has three operational layers:

### Query Stack (HMS-free)

Impala + Kudu without the Hive Metastore, HDFS, or HBase. Table metadata is managed through a PostgreSQL catalog registry (`KuduMetaProvider`, `SignalsDdlExecutor`). Kudu provides upsert-heavy hot-tier storage; Iceberg (via Polaris REST catalog) provides warm-tier analytics. Impala provides transparent SQL across both tiers. See [Query Engine](./architecture/query-engine.md).

### Metadata Governance

Atlas with a PostgreSQL + AGE graph backend (replacing JanusGraph/HBase/Solr) serves as the metadata catalog. A Python catalog bridge registers Impala-managed Kudu tables as Atlas entities. The `Tagger` service samples columns via Impala, classifies them against the SIGDG ontology, and writes classifications back to Atlas with confidence scores and evidence strings. See [Metadata Tagging](./architecture/meta-tagging.md).

### Classification Pipeline

The `sigint` Python package (20 modules, 363 unit tests) implements the full classification chain:

1. **Feature extraction** — 12 discrete, ablatable features per column (name, type, sample values, cardinality, entropy, pattern signals, sibling context, value description, etc.), each measured for marginal contribution via SAGE Shapley values
2. **Embedding classification** — Sentence-transformer embeddings with cosine similarity to taxonomy references
3. **CatBoost training** — Gradient boosting on 992-dim feature vectors, trained on synthetic data (70+ value generators, 50/50 semantic/opaque name split)
4. **Evidence fusion** — Dempster-Shafer mass functions from 4 sources combined via Dempster's rule, yielding belief intervals at every hierarchy level
5. **SAGE analysis** — Shapley Additive Global importancE quantifies each feature's marginal accuracy contribution, replacing intuition with measured values

See [Context Engineering](./architecture/context-engineering.md), [Evidence Fusion](./architecture/evidence-fusion.md), and [Heuristic Elucidation](./architecture/heuristic-elucidation.md).

## Ontology

The SIGDG ontology (Signals Data Governance) is grounded in BFO 2020. Information entities are `generically dependent continuants` (BFO:0000031); sensitivity levels are `qualities` (BFO:0000019) that inhere in them; data subject roles are `roles` (BFO:0000023) allowing the same column to carry different sensitivity depending on whose data it is. The taxonomy has 42 categories across 6 top-level kinds (Identity, Personal, Business, System, Transaction, Transformation) with 30 leaf nodes and 4 sensitivity levels (Public → Internal → Confidential → Restricted). See [SIGDG Ontology](./reference/sigdg-ontology.md).

## Scenarios

The project validates behavior through BDD scenarios (behave framework) organized into tiers:

| Tier | Domain | Scenarios | Status |
|------|--------|-----------|--------|
| **Tier 0** | Classification pipeline — embedding, evidence fusion, features, taxonomy, config, benchmarks | 40 | Passing |
| **Tier 1** | Component health — PostgreSQL, Kerberos, Kudu, Impala, Atlas | 22 | Passing |
| **Tier 1** | Integration — catalog sync, meta-tagging, pipeline tagging | 12 | Passing |
| **Planned** | Data lifecycle — hot→warm Kudu→Iceberg via CTAS | 5 | In progress |
| **Backlog** | Agent visualization, algorithm extension, self-improvement, OTel RCA, cybersec, streaming ontology | ~29 | Archived |

The tier-0 classification scenarios run offline with no infrastructure dependencies. Tier-1 scenarios require the full devenv stack (PostgreSQL, Kerberos KDC, Kudu, Impala, Atlas). All scenarios execute in air-gap mode (`HF_HUB_OFFLINE=1`) with pre-cached models — zero external network calls. See [Test Infrastructure](./scenarios/testing.md) and [Scenarios Overview](./scenarios/overview.md).

## Deployment

Four deployment modes from laptop to full AWS, with air-gap support via Zarf:

| Mode | Infrastructure | Best For |
|------|---------------|----------|
| **Laptop** | devenv (PostgreSQL, KDC, Kudu, Impala, Atlas) | Development, tier-0/tier-1 BDD |
| **Workstation** | devenv + optional RKE2 | Integration testing, GPU workloads |
| **Hybrid** | Local devenv + AWS RKE2 | Distributed compute |
| **Full AWS** | AWS EC2 + RKE2 | Production, air-gap |

ML model artifacts (sentence-transformer, ~80MB) are pre-cached locally and can be packaged into Zarf archives for disconnected environments. See [Deployment Modes](./architecture/deployment.md) and [Air-Gap (Zarf)](./infrastructure/zarf.md).

## Research Directions

The evidence fusion layer has an explicit [Research Roadmap](./reference/research-roadmap.md) addressing known limitations:

- **Source independence** (P0) — Cosine and CatBoost sources share the embedding space, weakening the independence assumption required by Dempster's rule. Confidence gating mitigates but does not eliminate this. Options include merging into a single source, decoupling feature spaces, or switching to a cautious combination rule (Denoeux, 2008).
- **Calibration** (P0) — 13 hardcoded discount constants lack empirical justification. Sensitivity analysis and Bayesian optimization against held-out data are planned.
- **Cautious hierarchical classification** (P1) — The pignistic transform always commits to a leaf singleton, discarding the hierarchy's value when evidence supports a parent but is ambiguous among children. A threshold-based approach following Denoeux & Zouhal (2001) would return the deepest node where \\(Bel(A) > \tau\\).

## Documentation Structure

- **[Architecture](./architecture/overview.md)** — system design, query engine, metadata tagging, evidence fusion, context engineering
- **[Scenarios](./scenarios/overview.md)** — BDD feature specifications, active and backlog domains
- **[Test Infrastructure](./scenarios/testing.md)** — tier system, air-gap testing, config-driven BDD
- **[Infrastructure](./infrastructure/overview.md)** — deployment, provisioning, air-gap packaging
- **[Components](./components/overview.md)** — Apache data infrastructure (Atlas, Ranger, Kudu, Impala, Iceberg)
- **[Operations](./operations/overview.md)** — development environment, services, Kerberos
- **[Reference](./reference/configuration.md)** — SIGDG ontology, configuration, research roadmap, implementation roadmap
