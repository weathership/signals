# Heuristic Elucidation

Each classification dataset presents unique properties — naming conventions, column structure, value distributions — that affect classifier performance in dataset-specific ways. Rather than treating techniques as ad-hoc fixes, the pipeline follows a systematic methodology: **observe** a phenomenon, **hypothesize** a mechanism, **implement** it as a feature or technique, **quantify** its contribution with SAGE, and **validate** across benchmarks.

We call this cycle *de novo heuristic elucidation*: the disciplined reduction of observed dataset-specific phenomena to practice, with measured contribution to overall accuracy.

This page ties together the three classification architecture pages — [Context Engineering](./context-engineering.md), [Classification Training](./classification-training.md), and [Evidence Fusion](./evidence-fusion.md) — by documenting the methodology that produces the features, techniques, and evidence sources they describe.

## The Methodology Cycle

```d2
direction: right

observe: "Observe\nRun benchmark\nIdentify failure modes" {
  style.fill: "#fce4ec"
}

hypothesize: "Hypothesize\nFormulate phenomenon\nas feature/technique" {
  style.fill: "#fff3e0"
}

implement: "Implement\nAdd to CatBoost features\nor post-processing" {
  style.fill: "#e8f4f8"
}

quantify: "Quantify\nSAGE Shapley values\nmeasure contribution" {
  style.fill: "#f0e8f8"
}

validate: "Validate\nCross-benchmark\ncomparison" {
  style.fill: "#e8f8e8"
}

observe -> hypothesize: "what's failing?"
hypothesize -> implement: "how to fix it?"
implement -> quantify: "does it help?"
quantify -> validate: "does it generalize?"
validate -> observe: "new failure modes"
```

Each step is concrete:

1. **Observe**: Run the pipeline on a benchmark dataset. Examine accuracy by column kind (data vs. annotation), by category group, and by naming convention. Identify where accuracy drops below baseline expectations.

2. **Hypothesize**: Formulate the failure mode as a testable phenomenon. "Annotation columns fail because the column name carries no semantic signal" is a hypothesis. "The training set has only 2 samples per class" is another.

3. **Implement**: Reduce the hypothesis to a feature (added to the CatBoost feature vector) or a technique (added to the pipeline). Every implementation must be expressible as a SAGE-ablatable feature or a measurable pipeline stage.

4. **Quantify**: Run SAGE to estimate the new feature's Shapley value — its marginal contribution to accuracy across all columns. Features with near-zero SAGE importance are noise; features with high importance validate the hypothesis.

5. **Validate**: Test the technique on a second benchmark with different properties. A technique that helps on the meta-tagging dataset but hurts on GitTables reveals a dataset-specific assumption that needs gating.

## Heuristic Catalog

Seven heuristics have been discovered through this cycle. Each row links to the architecture page where the technique is described in detail.

| # | Heuristic | Observation | Implementation | Generalizes? |
|---|-----------|-------------|----------------|-------------|
| 1 | [Dual embedding](./classification-training.md#dual-embedding) | Annotation columns have opaque names; the full embedding encodes a misleading name signal | Second embedding with name, table, and siblings stripped (value-only); concatenated as 384 additional dims | Yes |
| 2 | [Category reference augmentation](./classification-training.md#category-reference-augmentation) | 175 classes with ~2 real samples each; CatBoost cannot learn class boundaries | Inject 212 taxonomy reference embeddings as anchor training points | Yes |
| 3 | [Cosine similarity features](./classification-training.md#cosine-similarity-features) | Cosine similarity to category references is a strong zero-shot signal on semantic names | Encode 212 cosine similarities as CatBoost input features, bridging zero-shot and trained classifiers | Yes |
| 4 | [Paired column propagation](./classification-training.md#paired-column-propagation) | Data and annotation columns are structurally paired; the annotation follows its data column | Post-prediction pass: propagate confident data-column predictions to uncertain annotation columns | No — dataset-specific |
| 5 | [Value description](./context-engineering.md#feature-decomposition) | Generic names (`col0`, `field_1`) have no semantic content; cosine similarity on these is random | Substitute NL descriptions of value patterns when the column name is generic (12th SAGE feature) | Yes |
| 6 | [Discrete feature scaling](./classification-training.md#discrete-feature-scaling) | 12 discrete features are ignored by gradient boosting when 384-dim embedding vectors dominate split gain | Scale discrete features by \\(\sqrt{384/12}\\) so magnitudes compete | Yes |
| 7 | [Synthetic data generation](./classification-training.md#why-synthetic-training) | The evaluation data was procedurally generated from annotations; the generation process is reverse-engineerable | 70+ value generators covering all 175 categories, with 50/50 semantic/opaque name split | Partially |

### Generalization Status

Heuristics 1-3, 5-6 are **universally applicable** — they address structural properties (class imbalance, feature scale mismatch, uninformative names) that arise in any column classification task.

Heuristic 4 (paired propagation) is **dataset-specific**: it exploits a structural property of the meta-tagging dataset where each data column is followed by its annotation counterpart. Other datasets may have different column relationships that warrant different propagation heuristics — but the *methodology* of exploiting structural relationships is universal.

Heuristic 7 (synthetic data generation) applies when the evaluation data's generation process is known or inferable. For production data with unknown provenance, the role of synthetic generation shifts to LLM bootstrapping — the LLM classifies a sample of real columns to produce training signal.

## Cross-Benchmark Validation

Two benchmarks with complementary properties test whether heuristics generalize:

| Property | Meta-tagging dataset | GitTables CTA benchmark |
|----------|---------------------|------------------------|
| Column names | 50% semantic (`payment_card_number`), 50% opaque (`attr_1_1_2_1_3`) | 100% generic (`col0`, `col1`, empty) |
| Taxonomy | SIGDG (175 leaves, BFO-grounded) | DBpedia (122 types) |
| Column count | 350 (with GT labels) | 2517 (with GT labels) |
| Source | Annotated enterprise dataset | Academic benchmark (SemTab 2021) |

### Method Accuracy by Benchmark

| Method | Meta-tag (data cols) | Meta-tag (ann cols) | Meta-tag (overall) | GitTables |
|--------|---------------------|--------------------|--------------------|-----------|
| Cosine (zero-shot) | **99.4%** | 8.0% | 53.7% | 1.6% |
| CatBoost (standalone) | 66.3% | 29.7% | 48.0% | **81.6%** |
| DST fusion | — | — | — | 71.4% |
| Union ceiling | — | — | 66.0% | — |

The cross-benchmark comparison reveals three regimes:

1. **Cosine dominates** (meta-tag data columns): Semantic column names directly match category labels. Cosine similarity achieves 99.4% accuracy. CatBoost adds noise.

2. **CatBoost dominates** (GitTables, meta-tag annotation columns): Column names are uninformative. CatBoost trained on value patterns achieves 81.6% on GitTables. Cosine adds pure conflict (K > 0.5 on 100% of GitTables columns).

3. **Methods are complementary** (meta-tag overall): The union of correct answers reaches 66.0% — 12 points above either method alone. A well-tuned DST fusion captures both.

### Confidence-Gated Fusion

The regimes map to a principled DST integration rule: use cosine evidence's own confidence to decide how to weight it against CatBoost.

| Cosine Confidence | Regime | Action |
|-------------------|--------|--------|
| > 0.35 | High — cosine is reliable | Discount CatBoost |
| 0.05 - 0.35 | Medium — both contribute | Standard DST combination |
| < 0.05 | Low — cosine has no signal | Discount cosine |

This is the *confidence-gated fusion* pattern. It resolves the source independence concern ([R-01](../reference/research-roadmap.md)) by recognizing that cosine and CatBoost share the embedding space but contribute discriminatively in different regimes. Rather than always combining or always choosing one, the gate selects the regime where each source adds value.

The DST conflict metric \\(K\\) provides the runtime diagnostic: when \\(K > 0.5\\), the sources disagree enough that one should be discounted. On GitTables, 100% of columns have \\(K > 0.5\\) — a clear signal that cosine should be discounted. On meta-tagging data columns, \\(K\\) is moderate (mean 0.47) — the sources agree enough for standard combination.

## Agentic Integration

The heuristic elucidation cycle maps to an agentic workflow where frontier LLMs play the roles of observer, hypothesis generator, and training-signal bootstrapper:

```d2
direction: down

llm: "Frontier LLM" {
  style.fill: "#f0e8f8"

  observe: "1. Observe\nExamine new dataset\nIdentify phenomena"
  hypothesize: "2. Hypothesize\nFormulate as feature"
  bootstrap: "3. Bootstrap\nClassify sample columns\nGenerate training signal"
}

pipeline: "Classification Pipeline" {
  style.fill: "#e8f4f8"

  catboost: "CatBoost\nTrain on LLM labels"
  dst: "DST Fusion\nCombine evidence"
  sage: "SAGE\nMeasure contribution"
}

gate: "Quality Gate\nSAGE importance > 0?\nConflict K < threshold?" {
  style.fill: "#e8f8e8"
}

accept: "Accept Feature\nIncorporate permanently" {
  style.fill: "#e8f8e8"
}

reject: "Reject Feature\nDocument why it failed" {
  style.fill: "#fce4ec"
}

llm.observe -> llm.hypothesize
llm.hypothesize -> pipeline.catboost: "new feature"
llm.bootstrap -> pipeline.catboost: "training labels"
pipeline.catboost -> pipeline.dst
pipeline.dst -> pipeline.sage
pipeline.sage -> gate

gate -> accept: "SAGE > 0"
gate -> reject: "SAGE ≈ 0"
accept -> llm.observe: "next iteration"
reject -> llm.observe: "try different\napproach"
```

### Role of Each Component

**LLM as observer**: Given a new dataset, the LLM examines column names, value distributions, table structure, and identifies phenomena. For example: "these columns appear to be paired — each semantic column is followed by an opaque annotation column with the same values."

**LLM as bootstrapper**: The LLM classifies a sample of columns to generate training signal for CatBoost, replacing manual ground-truth labeling. This is the target design for production deployment — the LLM runs once to create training data, then the transparent CatBoost+DST pipeline handles ongoing classification without LLM dependency.

**SAGE as quality gate**: After implementing a new feature, SAGE automatically measures whether it improved accuracy. Features with near-zero Shapley values are noise — they should be discarded regardless of how plausible the hypothesis seemed. This prevents accumulation of heuristics that seemed helpful on one dataset but don't generalize.

**DST conflict as disagreement detector**: When a new evidence source conflicts with existing sources (\\(K > 0.5\\)), the conflict metric flags it for review. High conflict doesn't necessarily mean the new source is wrong — it may mean the confidence gate needs adjustment. But it does mean the sources should not be naively combined.

### Self-Improving Pipeline

The agentic workflow creates a self-improving classification pipeline: each new dataset encounter produces new heuristic candidates, which are automatically validated by SAGE and incorporated (or rejected) based on measured contribution. The LLM's role shifts from *classifier* to *methodology driver* — it doesn't classify columns directly in production, but it discovers the features and training signal that make CatBoost+DST effective.

## Relationship to Research Roadmap

Several items on the [research roadmap](../reference/research-roadmap.md) are consequences of the heuristic elucidation methodology:

| Research Item | Connection |
|---------------|------------|
| [R-01: Source Independence](../reference/research-roadmap.md) | Confidence-gated fusion is the principled response to shared embedding space between cosine and CatBoost |
| [R-02: Calibration Experiment](../reference/research-roadmap.md) | Calibrating the 13 DST constants requires cross-benchmark data — heuristic validation produces this data |
| [R-05: Cautious Classification](../reference/research-roadmap.md) | When no heuristic resolves a leaf-level ambiguity, cautious classification returns the deepest confident hierarchy node |
| [R-08: Confusable Pairs](../reference/research-roadmap.md) | The 16 remaining errors (ADID/GUID, BAN/PAN, etc.) are phenomena that no current heuristic resolves — they define the next cycle |

The research roadmap is not a static list but a **backlog of unresolved observations** from previous heuristic elucidation cycles. Each completed research item either produces a new heuristic or validates that a phenomenon is irreducible (e.g., ADID and GUID values are structurally identical — no embedding-based feature can distinguish them without external context).
