# Bootstrap Agent

The bootstrap agent is an LLM-driven pipeline for classifying novel databases when no ground truth exists. It uses DST conflict K as a convergence signal between LLM classifications and ML pipeline predictions, producing ground truth that feeds directly into the self-training pipeline.

## Problem

When a novel database arrives — real tables with no codes in column names, no label columns, no pre-existing ground truth — the ML pipeline has no training signal. Manual classification of thousands of columns is infeasible. The bootstrap agent solves this cold-start problem by using an open-weights LLM as a zero-shot classifier, validating outputs through 5-source DST fusion, and iteratively refining disagreements until convergence.

## Architecture

```d2
direction: down

novel: "Novel Database\n(CSV / Parquet)" {
  style.fill: "#e8f4f8"
  tooltip: "Input: one or more tables\nwith column metadata and sample values"
}

discover: "Schema Discovery" {
  style.fill: "#f0e8f8"
  tooltip: "Structural analysis before LLM classification"

  patterns: "11 Data Element\nPatterns" {
    tooltip: "PaymentCard, PostalAddress,\nPersonName, ContactInfo, etc."
  }
  fk: "FK Hint\nDetection" {
    tooltip: "entity_id → table name matching\nwith singular/plural handling"
  }
  batching: "Table-Aware\nGrouping" {
    tooltip: "Group columns by source table\nfor coherent LLM context"
  }
}

llm: "Phase 1: LLM Sweep" {
  style.fill: "#e8f4f8"
  tooltip: "Zero-shot classification of all columns"

  model: "Open-Weights LLM\n(GLM-4.7 / Devstral)" {
    tooltip: "50 cols/call, JSON response\nretry with exponential backoff"
  }
  prompt: "Table Context +\nDE Membership +\nSiblings + Values" {
    tooltip: "Structured prompt with taxonomy,\ntable name, data elements, siblings"
  }
  parse: "JSON Response\nParsing" {
    tooltip: "Primary + alternatives → mass function\nLenient regex fallback for smaller models"
  }
}

propagate: "Label Propagation\n(embedding sim > 0.85)" {
  style.fill: "#f0e8f8"
  tooltip: "Spread LLM labels to similar unlabeled columns\nvia MiniLM-L6 cosine similarity"
}

ml: "Phase 2: ML Validation" {
  style.fill: "#e8f4f8"
  tooltip: "Independent evidence from 5 orthogonal sources"

  cosine: "Cosine" {tooltip: "Embedding similarity"}
  catboost: "CatBoost" {tooltip: "992-dim gradient boosting"}
  pattern: "Pattern" {tooltip: "8 regex detectors"}
  name: "Name" {tooltip: "String matching"}
  svm: "SVM" {tooltip: "TF-IDF char n-grams"}
  combine: "Dempster's Rule\n→ conflict K" {
    tooltip: "Conjunctive combination\nnormalized by 1/(1-K)"
    style.fill: "#fff3e0"
  }
}

decision: "Convergence Check\nK < 0.2?" {
  style.fill: "#fff3e0"
  tooltip: "Low K = agreement, high K = disagreement\nAlso checks coverage and budget"
}

revisit: "Phase 3: Targeted Revisit" {
  style.fill: "#fce4ec"
  tooltip: "Re-classify only high-K columns\nwith enriched ML context"

  context: "ML prediction +\nbelief interval +\nconfusable pairs +\nprevious LLM answer" {
    tooltip: "LLM sees what ML thinks and why"
  }
}

refine: "DE Refinement\n(category co-occurrence)" {
  style.fill: "#f0e8f8"
  tooltip: "Discover data elements from\nclassification results, not just names"
}

gt_out: "bootstrap_gt.json" {
  style.fill: "#e8f8e8"
  tooltip: "{column: category_code}\nwith source_map provenance"
}

de_out: "data_elements.json" {
  style.fill: "#e8f8e8"
  tooltip: "DataElement catalog with\nnaming + co-occurrence sources"
}

selftrain: "Self-Train Pipeline\n(CatBoost → 99.4%)" {
  style.fill: "#e8f8e8"
  tooltip: "Deterministic, explainable,\nzero marginal cost at scale"
}

novel -> discover
discover.patterns -> discover.batching
discover.fk -> discover.batching
discover.batching -> llm.prompt
llm.prompt -> llm.model
llm.model -> llm.parse
llm.parse -> propagate
propagate -> ml

ml.cosine -> ml.combine
ml.catboost -> ml.combine
ml.pattern -> ml.combine
ml.name -> ml.combine
ml.svm -> ml.combine
ml.combine -> decision

decision -> revisit: "K > 0.2" {style.stroke: "#e53935"}
decision -> refine: "K < 0.2" {style.stroke: "#43a047"}
revisit.context -> ml: "re-validate\n(loop ≤ 5×)" {style.stroke-dash: 3}

refine -> gt_out
refine -> de_out
gt_out -> selftrain
```

## Three-Phase Architecture

### Phase 1: LLM Sweep

The LLM classifies all columns in a single pass using table-aware batching. Each batch prompt includes:

- **Table name** and discovered data elements for context
- **Column metadata**: name, type, sample values, sibling columns, DE membership
- **Full taxonomy** as a markdown table (code, label, description)
- **Instructions** to return a JSON array with primary classification, confidence, evidence, and up to 3 alternatives

The alternatives field is critical — it feeds directly into `llm_to_mass()` where the primary prediction and alternatives are converted into a Dempster-Shafer mass function with calibrated uncertainty.

**Batch mechanics:**

| Parameter | Value |
|-----------|-------|
| Columns per call | 50 (configurable) |
| Max tokens | 65,536 (required for reasoning models) |
| Temperature | 0.0 (deterministic) |
| Retry logic | 3 attempts, exponential backoff (2s → 4s → 8s) on 429/502/503/504 |
| Truncation detection | `finish_reason == "length"` triggers warning |

### Phase 2: ML Validation

After LLM labels are assigned, the ML pipeline runs as a **validator**. It produces independent evidence from 5 orthogonal sources and combines them via Dempster's rule. The key output is **conflict K** — a rigorous measure of how much the sources disagree.

A column is flagged for revisit when **both** conditions hold:

1. The LLM label differs from the ML prediction: `llm_code != ml_code`
2. The DST conflict exceeds the threshold: `K > k_threshold` (default 0.2)

### Phase 3: Targeted Revisit

When disagreements exist, the agent re-sends only contentious columns to the LLM with enriched context from the ML validation. The convergence loop iterates up to `max_iterations` (default 5) times with three exit conditions: all resolved, budget exhausted, or mean K below threshold.

## Schema Discovery & Data Elements

Before the LLM sees any columns, the system performs structural analysis to discover **Data Elements** — composite semantic concepts that span columns across one or more tables.

### Data Element Pattern Library

11 well-known patterns across 7 governance domains:

| Data Element | Domain | Indicators | Min Match |
|-------------|--------|------------|-----------|
| PaymentCard | finance | card_number, pan, cvv, expiry, cardholder | 2 |
| PostalAddress | contact | street, city, state, zip, postal_code, country | 2 |
| PersonName | identity | first_name, last_name, full_name, middle_name | 2 |
| ContactInfo | contact | email, phone, mobile, fax, telephone | 2 |
| BankAccount | finance | account_number, routing_number, iban, swift | 2 |
| GovernmentID | identity | ssn, passport, driver_license, tax_id, ein | 2 |
| BiospecimenCollection | healthcare | sample_location, specimen_type, collection_date | 2 |
| PatientDemographics | healthcare | date_of_birth, gender, ethnicity, blood_type, mrn | 2 |
| GeoLocation | spatial | latitude, longitude, coordinates, altitude | 2 |
| DeviceIdentity | technology | device_id, mac_address, ip_address, imei | 2 |
| Credential | security | password, pin, secret, token, api_key | 2 |

### Table-Aware Batching

When `table_aware_batching = true` (the default), columns are grouped by source table instead of flat slices. This ensures the LLM prompt includes a `## Table: payments` header and lists discovered data elements, giving the model coherent schema context.

### FK Hint Detection

Columns named `<entity>_id` (e.g., `instrument_id`) are matched against table names (`instruments`) with singular/plural handling, identifying cross-table relationships that inform data element membership.

### Post-Classification DE Refinement

After bootstrap classification, a second pass discovers data elements that naming patterns missed — using **category co-occurrence** within tables. Known category combinations (e.g., PAN + Name + Address → PaymentCard) trigger new data element emissions with `source="co-occurrence"`.

## Label Propagation

After LLM labels, similar unlabeled columns receive the same label via embedding cosine similarity. This exploits the SAGE finding that `column_name` accounts for 53% of classification signal — columns with similar names and values likely share the same category.

Propagation rules:
- Only from LLM-direct labels (no cascading)
- Cosine similarity > 0.85 (configurable)
- Skip if ML strongly disagrees (confidence > 0.5 and different code)

After all LLM phases complete, any remaining unlabeled columns with high ML confidence (>= `confidence_floor`) receive the ML prediction as their label. Every label carries a `source_map` entry tracking provenance: `"llm"`, `"llm_revisit"`, `"propagated"`, or `"ml"`.

## LLM Revisit

When the LLM and ML disagree on a column AND K is high, the column is re-sent to the LLM with enriched context:

```
### Column 3: account_number (REVISIT)
Type: STRING | Values: ["1234567890", "9876543210"]
Siblings: [customer_name, routing_number, balance]
Data elements: [BankAccount]
ML prediction: BankAccountNumber [Bel=0.35, Pl=0.68, K=0.31]
Confusable: BankAccountNumber / PaymentAccountNumber
Your previous: PaymentAccountNumber (conf=0.65)
```

This gives the LLM three pieces of information it didn't have before:

1. **ML prediction with belief interval** — what the evidence sources think, with calibrated uncertainty
2. **Confusable pair** — the specific known ambiguity between categories
3. **Its own previous answer** — a reminder of what it said and at what confidence

## LLM Backends

The agent supports three LLM backends via the OpenAI chat completions protocol:

| Backend | Model | Use Case |
|---------|-------|----------|
| `cerebras` | GLM-4.7 (358B MoE, open-weights) | Default — fast inference, reproducible |
| `anthropic` | Claude Opus 4.6 | Cloud deployment |
| `openai_compatible` | Devstral Small 2 / any | Air-gap (vLLM, Ollama, etc.) |

All backends use the same batch prompt format and JSON response parsing. The OpenAI-compatible backend includes lenient parsing (regex fallback) for smaller models.

**GLM-4.7** is the default because it is an open-weights model — critical for reproducibility and on-premises deployment in air-gapped environments. The same weights can run via cloud inference APIs or locally via vLLM/TGI, ensuring identical classification behavior regardless of deployment mode. Its reasoning capability (chain-of-thought) improves classification accuracy on ambiguous columns, though it consumes ~80-85% of output tokens on reasoning, requiring `llm_max_tokens >= 65536`.

## LLM as DST Evidence Source

The LLM's predictions become proper mass functions via `llm_to_mass()`, not overrides:

| Source | Discount | Independence |
|--------|----------|-------------|
| Cosine | 0.30 | Embedding similarity |
| CatBoost | 0.15 | Gradient boosting on features |
| Pattern | 0.10 | Regex detection |
| Name match | 0.30-0.70 | Lexical matching |
| SVM | 0.20 | TF-IDF sparse features |
| **LLM** | **0.10** | **Full contextual reasoning** |

The low discount (0.10) reflects the LLM's high reliability. DST conflict K between LLM and ML sources is a genuine disagreement signal.

## Configuration

All bootstrap parameters flow through HOCON (`config/base.conf`):

| Key | Default | Description |
|-----|---------|-------------|
| `bootstrap.max_iterations` | 5 | Max convergence loop iterations |
| `bootstrap.k_threshold` | 0.2 | DST K threshold for LLM revisit |
| `bootstrap.uncertainty_gap_threshold` | 0.3 | Pl - Bel gap threshold |
| `bootstrap.coverage_target` | 0.95 | Target label coverage |
| `bootstrap.confidence_floor` | 0.5 | Min ML confidence for fallback labels |
| `bootstrap.initial_sample_fraction` | 0.3 | Initial LLM sample size fraction |
| `bootstrap.propagation_similarity` | 0.85 | Cosine sim for label propagation |
| `bootstrap.max_llm_calls_per_iteration` | 500 | Per-iteration LLM call cap |
| `bootstrap.max_total_llm_calls` | 5000 | Total LLM call budget |
| `bootstrap.columns_per_call` | 50 | Batch size per LLM call |
| `bootstrap.output` | `build/bootstrap_gt.json` | Ground truth output path |
| `bootstrap.llm_backend` | cerebras | LLM provider |
| `bootstrap.llm_api_key` | null | API key (env var fallback) |
| `bootstrap.llm_base_url` | null | Custom base URL |
| `bootstrap.llm_model` | (from `llm.model`) | Model name |
| `bootstrap.llm_max_tokens` | 65536 | Max response tokens |
| `bootstrap.llm_discount` | 0.10 | LLM evidence discount in DST |
| `bootstrap.table_aware_batching` | true | Group columns by table |

## Integration with Self-Training

The bootstrap output feeds directly into the self-training pipeline:

```bash
# Step 1: Bootstrap — produce initial ground truth
uv run python scripts/bootstrap_classify.py \
    --data-dir ~/data/novel_tables/ \
    --data-elements \
    --output build/bootstrap_gt.json

# Step 2: Self-train — produce production model
uv run python scripts/build_sigint_embeddings.py \
    --data-dir ~/data/novel_tables/ \
    --ground-truth build/bootstrap_gt.json \
    --self-train --auto-generate \
    --output build/sigint_final.parquet
```

The `--data-elements` flag enables schema discovery and data element output alongside the ground truth JSON. The self-trained CatBoost model learns to reproduce LLM classifications with 99.4% fidelity — providing deterministic inference, per-item SHAP explanations, calibrated belief intervals, and zero marginal cost at scale.

## Key Files

| File | Purpose |
|------|---------|
| `src/sigint/bootstrap_agent.py` | 3-phase agent: LLM sweep → ML validation → targeted revisit |
| `src/sigint/llm_backend.py` | LLM abstraction: Anthropic, OpenAI-compatible, Cerebras factory |
| `src/sigint/schema_discovery.py` | 11 DE patterns, FK hints, category co-occurrence refinement |
| `src/sigint/data_element.py` | DataElement, DataElementMember, DataElementCatalog |
| `src/sigint/mass_functions.py` | `llm_to_mass()` converter |
| `scripts/bootstrap_classify.py` | CLI entry point |
| `config/base.conf` | HOCON configuration (18 bootstrap keys) |
