# Two-tier schema redesign: Kudu tier0 + HDF5-in-Iceberg tier1

Guru: `#SL.00000027.SCHEMA2`

Scope: one telemetry model spanning DCGM, vLLM, and (later) CLT/SAE feature
activations and inter-agent captured latents. Settled before implementing
HDF5 predicate evaluation, because the predicate work is only as good as the
physical layout it reads.

## Constraints that actually decided the design

Measured on this tree, not assumed:

| Constraint | Source | Consequence |
|---|---|---|
| Kudu cell cap **64 KB**, `TAG_FLAG(unsafe)` | `row_operations.cc:50-54` | Applies to arrays too — they are BINARY physical, so `ptr_slice->size()` is checked at `:304` before the array block at `:318`. |
| Array cap **1024 elements** (default) | `row_operations.cc:56` `array_cell_max_elem_num`, enforced `:321` | Second, independent cap. Tunable and *not* unsafe-tagged; `row_operations-test.cc:1159` exercises `64 * 1024` as a boundary. |
| **Kudu does not predicate arrays** | `025126_kudu-array-hs2-fdw-types.md` | Arrays are payload-only. Every filterable dimension must be a scalar column. |
| Arrays are 1-D only, no nested, no DECIMAL128, no SERIAL element | `client/schema.cc:547` | Sparse vectors must be *two parallel arrays*, not an array of structs. |
| Arrays cannot be key columns | `kudu_create.test:752` | Vector payload never participates in the PK. |
| Arrays accept encoding/compression | `client/schema.cc:540-565` (element type flows through) | `LZ4` on array columns is available. |
| HS2 `CREATE ... STORED AS KUDU` SIGSEGVs the tserver | 415 crashes 2026-08-24 17:38→18:57 | **All creation goes through the C++ client.** Non-negotiable. |
| STRING in PK + nullable non-PK were the other deviations in that outage | same | New PKs are all-INT, NOT NULL. |

## Tier 0 — Kudu

Two tables, not one per product. The metric set churns (17 DCGM families,
~25 vLLM, more later); a column-per-metric table would need an `ALTER` per
change on a table we have learned is expensive to get wrong. Narrow + dictionary
encoding costs ~2 bytes/row for the name and never needs migration.

### `signal_tier0` — every scalar sample

```
epoch_hour  INT32   NOT NULL  RLE           PK
ts_ns       INT64   NOT NULL  BIT_SHUFFLE   PK
series_id   INT64   NOT NULL  BIT_SHUFFLE   PK
src         INT8    NOT NULL  RLE            0=dcgm 1=vllm 2=engine 3=host
gpu         INT8    NULL      RLE            GPU ordinal when applicable
inst        INT16   NULL      RLE            endpoint/instance ordinal
series      STRING  NOT NULL  DICT           'dcgm.power_w', 'vllm.kv_cache_usage'
val         DOUBLE  NOT NULL  BIT_SHUFFLE
PRIMARY KEY (epoch_hour, ts_ns, series_id)
HASH (series_id) 4 BUCKETS
RANGE (epoch_hour) — day-wide bounds
```

- `series_id` is a stable 64-bit hash of the canonical series name: deterministic
  at write time, no registry round-trip, negligible collision risk at ~150 series.
- PK is time-major so the waterfall's "all series, last 60 s" is one contiguous
  scan; `series_id` last gives uniqueness *and* the hash key.
- Hashing on `series_id` is what keeps a monotonic `ts_ns` from hot-spotting a
  single tablet — the failure mode the Kudu schema guide calls out first.
- `val DOUBLE`, not FLOAT: `DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION` is mJ since
  boot and is already ~10^10. float32 would lose integer precision on it.

### `latent_tier0` — LatentMAS latent thoughts

Sized against **Qwen3-1.7B-Base**: `hidden_size` 2048, 28 layers, GQA 16 Q × 128
/ 8 KV × 128. A latent thought is the last-layer hidden state, so **2048-d**;
the transferred KV working memory is 1024-wide per layer per side (GQA), not
2048.

```
epoch_hour  INT32   NOT NULL  RLE          PK
ts_ns       INT64   NOT NULL  BIT_SHUFFLE  PK
stream_id   INT64   NOT NULL  BIT_SHUFFLE  PK   hash(agent, stream)
seq         INT32   NOT NULL  RLE          PK   row ordinal within the instant
kind        INT8    NOT NULL  RLE          0=thought 1=kv
layer       INT16   NULL      RLE          0..27
step        INT32   NULL      RLE          latent step
norm        FLOAT   NULL      BIT_SHUFFLE
stream      STRING  NOT NULL  DICT
agent       STRING  NOT NULL  DICT
model       STRING  NOT NULL  DICT         'Qwen/Qwen3-1.7B-Base'
ref         STRING  NULL      DICT         task/trace id
vec         FLOAT[] NULL      LZ4          thought hidden state, 2048
k_vec       FLOAT[] NULL      LZ4          GQA K, 1024 per layer
v_vec       FLOAT[] NULL      LZ4          GQA V, 1024 per layer
PRIMARY KEY (epoch_hour, ts_ns, stream_id, seq)
HASH (stream_id) 2 BUCKETS · RANGE (epoch_hour) day-wide
```

| Payload | Elements | Bytes f32 | vs 1024 elem | vs 64 KB |
|---|---|---|---|---|
| Thought hidden state | 2048 | 8 192 | **2× over** | fits |
| K or V, one layer | 1024 | 4 096 | at the line | fits |
| KV one step, all layers | d_h × L = 57 344 | 229 376 | far over | **3.5× over** |

Even a single 2048-d thought exceeds the *default* element cap. This table needs
`--array_cell_max_elem_num=4096` — a tunable, non-unsafe flag, well inside the
64 K the tests exercise. KV decomposes by `layer` (28 rows/step, 8 KB each),
which the 4-column PK absorbs unchanged: `seq` is the writer-assigned row
ordinal within the instant, so a KV step emits `seq=0..27` carrying
`layer=0..27`.

**KV is a cache, not ground truth.** A thought is 8 KB; its KV working memory is
224 KB — 28× more, exactly the paper's `d_h × L` bandwidth term. The thought
sequence plus `model` is the irreducible record; KV is recomputable by replaying
the model. Capture thoughts always, KV by opt-in or sampling.

### Partitioning budget

Day-wide range bounds on an hourly PK column (bounds need not be unit-width),
with a 3-day hot window:

| Table | buckets × ranges | tablets |
|---|---|---|
| `signal_tier0` | 4 × 3 | 12 |
| `latent_tier0` | 2 × 3 | 6 |
| **total** | | **18** |

Against today's `gpu_metrics_tier0` at 42 and climbing one hour at a time. The
`DROP RANGE PARTITION` valve now drops a *day* after its 24 HDF5 objects have
settled and verified.

**Kudu range width and HDF5 object width are deliberately decoupled**: Kudu
drops days (few tablets), tier1 writes hours (small, verifiable objects,
naturally keyed by `epoch_hour`). ~150 series × 3600 s ≈ 540 k rows/hour,
~3 MB compressed — a good HDF5 object size.

## CLT interpretability — reference tables, not time series

Correction to an earlier draft: **CLT output does not go to Kudu in full vector
form.** What is worth persisting is the per-feature `top_logits` signature, the
labels agents assign from it, and the activation events that tie text to
features. The governing fact is a *rate* difference:

> **Features are stable. Labels drift.** Agents re-label as the text under
> consideration changes; the feature index never moves.

And the retrieval requirement is explicitly historical: *retrieve a past
timeframe and understand how the agent applied the label to the text→feature
activation event.* That is a temporal join, which makes this a bitemporal
modelling problem, not a storage-size one.

### ⚠ Kudu UPSERT is the hazard here

Kudu makes overwriting a row trivial, and overwriting a label is exactly the
operation that destroys the history this requirement depends on. The label table
is **append-only, with `valid_from_ns` in the primary key**. There is no UPDATE
path. A re-label is a new row; "the label as of T" is the latest row with
`valid_from_ns <= T`.

### `clt_feature` — stable identity, never tiers

```
model_id     INT32   NOT NULL  RLE   PK   hash('clt-qwen3-1.7b-base-20k')
layer        INT16   NOT NULL  RLE   PK   0..27
feature_idx  INT32   NOT NULL  BIT_SHUFFLE  PK   0..20479
top_token_id INT32[] NOT NULL  LZ4        top-k promoted tokens
top_logit    FLOAT[] NOT NULL  LZ4        matching logits
decoder_norm FLOAT   NULL      BIT_SHUFFLE
PRIMARY KEY (model_id, layer, feature_idx)
HASH (feature_idx) 4 BUCKETS · no range partition
```

28 × 20 480 = 573 440 rows, written once per CLT model. `top_logits` at k=32 is
64 elements and ~256 bytes — comfortably inside *both* caps at their defaults.

### `clt_label` — append-only bitemporal

```
model_id     INT32   NOT NULL  RLE          PK
layer        INT16   NOT NULL  RLE          PK
feature_idx  INT32   NOT NULL  BIT_SHUFFLE  PK
valid_from_ns INT64  NOT NULL  BIT_SHUFFLE  PK   ← the anti-overwrite guard
label        STRING  NOT NULL  DICT
agent        STRING  NOT NULL  DICT
confidence   FLOAT   NULL      BIT_SHUFFLE
evidence_ref STRING  NULL      DICT   text/activation event that drove the label
supersedes_ns INT64  NULL      BIT_SHUFFLE
PRIMARY KEY (model_id, layer, feature_idx, valid_from_ns)
HASH (feature_idx) 4 BUCKETS · no range partition
```

Feature-major PK order means "every label this feature has ever carried" is one
contiguous scan, and the `valid_from_ns` suffix makes as-of-T a range predicate
on that scan.

### `clt_activation_tier0` — the text→feature event, and this one *does* tier

```
epoch_hour  INT32   NOT NULL  RLE          PK
ts_ns       INT64   NOT NULL  BIT_SHUFFLE  PK
text_id     INT64   NOT NULL  BIT_SHUFFLE  PK   hash of the text item
pos         INT32   NOT NULL  RLE          PK   token position
layer       INT16   NOT NULL  RLE          PK
feat_idx    INT32[] NOT NULL  LZ4          ~115 active
feat_val    FLOAT[] NOT NULL  LZ4
nnz         INT32   NOT NULL  BIT_SHUFFLE
agent       STRING  NULL      DICT
ref         STRING  NULL      DICT
PRIMARY KEY (epoch_hour, ts_ns, text_id, pos, layer)
HASH (text_id) 4 BUCKETS · RANGE (epoch_hour) day-wide
```

Sparse pairs at L0≈115 are 230 elements / ~920 bytes — inside both caps at their
defaults, and 115× fewer rows than one row per active feature. This is *sparse*,
not "full vector form": the dense alternative is 20 480 floats = 80 KB, over the
byte cap and 20× over the element cap.

`nnz` is a scalar because **Kudu cannot predicate arrays** — it is the only
handle that makes "positions where many features fired" answerable without
materialising a payload column.

### The query this exists to serve

> As of last Tuesday, how did the agent label the features that fired on this text?

```sql
SELECT a.text_id, a.pos, a.feat_idx, a.feat_val, l.label, l.agent
FROM clt_activation_tier0 a
JOIN LATERAL (
  SELECT label, agent FROM clt_label
  WHERE feature_idx = <f> AND valid_from_ns <= a.ts_ns
  ORDER BY valid_from_ns DESC LIMIT 1
) l ON true
WHERE a.epoch_hour BETWEEN <lo> AND <hi>;
```

Both predicates push down: `epoch_hour`/`ts_ns` prune partitions on the event
side, `feature_idx` is a PK prefix lookup on the label side. Neither touches an
array.

## ColBERT-Zero packing — open design space

ColBERT-Zero is text-only, ≤512 tokens, **128-d per token** (`colbert.py:27`,
`EMBEDDING_DIM = 128`; `config.py:84` records ColNomic as retired — the 768-d
Nomic figure in an earlier draft was vestigial).

A full 512-token embedding is 65 536 elements / 262 144 bytes fp32. Against the
two caps:

| Design | Elements/row | Bytes/row | Rows/doc | Flags needed |
|---|---|---|---|---|
| **(a)** row per token | 128 | 512 | 512 | **none** |
| **(b)** row per doc, fp32 | 65 536 | 262 144 | 1 | elem→64K **+ byte cap 4× (unsafe)** |
| **(c)** row per doc, int8 + scale | 65 536 | 65 536 | 1 | elem→64K; byte cap *marginal* |
| **(d)** chunk 64 tokens | 8 192 | 32 768 | 8 | elem→8192 |
| **(e)** chunk 112 tokens | 14 336 | 57 344 | 5 | elem→16384 |

Reading of each:

- **(b) is the one to avoid.** It needs `max_cell_size_bytes` raised 4×, and
  that flag is `TAG_FLAG(..., unsafe)`. Raising an unsafe tserver flag is the
  same category of change as the HS2 `CREATE` that cost us 415 SIGSEGVs on
  2026-08-24. Not without a soak.
- **(c) is the interesting research direction**, but it lands *exactly* on the
  64 KB line — 512 × 128 × 1 B = 65 536, and array cell metadata pushes it over.
  It fits only at ≤496 tokens. int8 is conservative for ColBERT (PLAID ships
  2–4-bit residual compression), and Kudu has no float16, so INT8[] plus a
  per-vector scale is the natural quantized form.
- **(d)/(e) get most of (c)'s row-count win with no unsafe flag and no
  quantisation.** Late interaction needs *all* token vectors of a candidate doc,
  so fewer/larger reads beat 512 small ones — but 8 reads and 1 read are much
  closer than 512 and 1.

**Recommendation:** baseline on **(d)**, benchmark **(c)** against it, skip (b).

### Zero-padding is a per-tier decision, not a global one

Padding to a fixed 512 **costs in Kudu and buys nothing there**: Kudu arrays are
already variable-length, so padding just inflates the common short-text case
toward the one cap it can least afford. Median KB text is far under 512 tokens.

Padding **does** buy in HDF5: a fixed `[N][512][128]` chunked dataset is exactly
what HDF5 is best at — direct hyperslab addressing with no offset index, and
gzip flattens the zero padding to almost nothing.

So: **ragged in tier0, padded in tier1.** The two tiers want opposite answers
and there is no reason to force one on both.

⚠ **Tension to resolve before choosing (c):** the union view's premise is
schema-identical tiers. If tier0 quantises to int8 and tier1 keeps fp32, the
UNION breaks. Either both quantise or neither — so (c) is a decision about the
*whole* stack, not just the hot tier.

**Prior question:** whether these belong in Kudu at all. Qdrant is the serving
index and supports multi-vector natively; the Kudu copy would be durable-record
and analytics only. Worth being explicit about what it buys before paying 8
rows/doc for it.

## Decimal instead of IEEE 754

Asked: can both tiers use decimal to avoid float artifacts? The answer splits by
**where the number came from**, and the split is principled rather than
pragmatic.

### Kudu decimal, measured

`client/schema.cc:144-150` — precision drives the backing width:

| Precision | Backing | Bytes | Array? |
|---|---|---|---|
| ≤ 9 | DECIMAL32 | **4** | yes |
| ≤ 18 | DECIMAL64 | **8** | yes |
| ≤ 38 | DECIMAL128 | 16 | **no** (`exec_kudu.cpp:227`) |

So decimal arrays are available up to p=18, and **DECIMAL(9,s) costs exactly
what fp32 costs**.

### Telemetry: decimal is *more faithful than float*, not merely equal

The strongest argument is not exactness-in-the-abstract — it is that the sources
are **already integral or fixed-point**, so DOUBLE introduces representation
error that was never in the measurement:

| Source | Native form |
|---|---|
| `GPU_UTIL`, `MEM_COPY_UTIL`, `ENC/DEC_UTIL` | integer percent |
| `GPU_TEMP`, `MEMORY_TEMP` | integer °C |
| `SM_CLOCK`, `MEM_CLOCK` | integer MHz |
| `TOTAL_ENERGY_CONSUMPTION` | integer mJ |
| `POWER_USAGE` | NVML milliwatts → 3 decimals |
| `FB_FREE`/`FB_USED` | integer MiB |
| vLLM counters, queue depths | integers |

Storing an integer percent as a double and reading it back is a round trip that
can only lose. Decimal stops the loss rather than adding precision.

Second win: **fixed-point addition is exact and associative.** `SUM`/`AVG` stop
depending on scan order, so tier0 and tier1 return bit-identical aggregates —
which is precisely the property the UNION view's credibility rests on.

**Choice: `val DECIMAL(18,6)`** — DECIMAL64, 8 bytes, the same width as the
DOUBLE it replaces. 12 digits before the point, 6 after.

⚠ **Requires canonical SI units, normalised at ingest.** DECIMAL(18,6) tops out
near ±10¹². Energy in **mJ** at 1500 W burns that in **7.7 days** of uptime;
in **joules** it lasts ~21 years. Declaring a canonical unit per series and
normalising on the way in is what makes one scale sufficient for every series —
and it retires a whole bug class (the mJ/J confusion) on the way past.

### HDF5 has no decimal type — and that turns out to be the elegant part

Store the **unscaled integer plus `@scale` as an attribute**, which is exactly
how Kudu represents decimal internally. The tiers then match *bit for bit*, not
merely numerically.

It also likely makes tier1 **smaller**. HDF5's shuffle filter groups byte-0s,
byte-1s, … together; slowly-varying fixed-point telemetry has near-constant
high bytes, so shuffle+gzip crushes it. Float64 mantissa low bits are noise and
shuffle helps far less. The usual "decimal costs more" intuition inverts here.

### Activations: decimal is a category error — except where it is free

Latent thoughts, KV, `top_logits` and ColBERT vectors are **IEEE 754 by
construction** — bf16/fp16/fp32 tensors out of the model. There is no truer
decimal value behind them that float is corrupting, and the non-associativity
worth worrying about lives upstream in the model's own matmuls, not in storage.
Paying for exactness here buys exactness about an already-inexact input.

**But ColBERT-Zero is the exception, and it is free.** Its vectors are
L2-normalised, so every component sits in [-1, 1]:

- `DECIMAL(9,8)` → DECIMAL32 → **4 bytes, identical to fp32**
- 9 significant decimal digits against fp32's ~7.2 — *more* precision in [-1,1]
- exact, associative accumulation

This is the direct answer to "I'd rather not quantise": decimal gets exactness at
fp32's price. It does **not** change the packing arithmetic — 512 × 128 × 4 is
still 262 144 B, still 4× over the unsafe byte cap — so the chunking decision
stands on its own.

Hidden states are *not* normalised (transformers carry massive-activation
outliers in the hundreds), so they need `DECIMAL(18,8)` → DECIMAL64 → 8 bytes,
2× fp32. A 2048-d thought becomes 16 KB and KV 16 KB/layer — both still inside
64 KB. Affordable, but optional: take it only for bit-identical tier round-trip
and reliable equality-dedup. Default fp32 and revisit.

`top_logits` at k=32 is 32 values; decimal there costs 256 bytes. Take it — the
UI reads those numbers and reproducibility is cheap.

### What this costs, and it is not nothing

1. **Decimal predicates do not push down.** `kudu_pred.c` contains no decimal
   handling at all. `WHERE val > 100` would fall back to a local filter — the
   same regression class as the parameterised-predicate bug just fixed
   (12.92 s → 0.01 s). Decimal is int-backed, so extending the existing integer
   predicate path is tractable, but **it must land before `val` becomes
   decimal**, not after.
2. **No NaN or ±Inf.** Wherever DCGM reports a field unavailable, ingest must
   write an explicit NULL instead of letting NaN propagate. Strictly better —
   NaN silently poisons aggregates — but it is a real migration step.
3. **Impala decimal arithmetic is slower than float SIMD.** Irrelevant for
   warehouse aggregation; convert to float at the serving boundary for MaxSim.

### Verdict

| Data | Representation | Rationale |
|---|---|---|
| `signal_tier0.val` | `DECIMAL(18,6)` + SI units | sources are integral; exact aggregation; same 8 B |
| ColBERT vectors | `DECIMAL(9,8)` | free — 4 B, more precision than fp32 in [-1,1] |
| `clt_feature.top_logit` | `DECIMAL(18,8)` | negligible size, user-visible numbers |
| CLT `feat_val` | `DECIMAL(18,8)` | 8 B; inside caps at L0≈115 |
| Latent thought / KV | `FLOAT` (revisit) | IEEE by origin; 2× cost for marginal gain |

**Blocking prerequisite:** decimal predicate pushdown in `kudu_pred.c`.

## Tier 1 — HDF5 in Iceberg

Today's tier1 is a hardcoded `nGpu × nTime` **int16** matrix at a fixed
`/Machine/GpuMetric[0]/Values` path. Two problems, one of them a live bug:

1. **int16 quantisation silently clips.** `generate_sdg_hdf5.py:157` forces
   `dtype=np.int16` on whatever the caller passes, and `:224-235` clips each
   plane to ±32767. Fine for watts and °C by luck; `mem_used_mb` (`:231`)
   survives only because these cards are 24 GB — an 80 GB card writes 81 920 and
   lands 32767 with no error. `TOTAL_ENERGY_CONSUMPTION` (~10^10 mJ) is already
   far past it. This is a live correctness bug, not a fidelity preference.
2. The fixed path and fixed grain cannot express latents, floats, or a varying
   series set.

Replacement is schema-driven and keeps the one property worth keeping — a
**sorted int64 time vector** as the index.

```
/signal
  ts         int64  [T]      sorted, unique instants
  series_id  int64  [S]      sorted
  series     str    [S]
  src        int8   [S]
  gpu        int8   [S]
  inst       int16  [S]
  values     float64[S][T]   chunked (S, 3600), shuffle + gzip
  present    uint8  [S][T]   presence bitmap — gaps stated, not imputed
  @ts_min @ts_max @n_series @n_time @schema_version

/latent
  ts         int64  [N]      sorted
  stream_id  int64  [N]
  seq        int32  [N]
  kind       int8   [N]
  layer      int16  [N]
  pos        int32  [N]
  norm       float32[N]
  vec        float32[N][D]        chunked (64, D)
  feat_idx   vlen<int32>  [N]     ragged
  feat_val   vlen<float32>[N]     ragged
  @ts_min @ts_max @dim @schema_version
```

float64 for signal values — no quantisation. HDF5 shuffle+gzip on slowly-varying
telemetry recovers most of what the int16 packing was buying, without the
correctness hazard.

## Why this layout is what predicate evaluation needs

`Hdf5ReadBuilder.filter()` and `.split()` are currently `return this` — a
filtered tier1 read returns *wrong answers*, not merely slow ones. This layout
makes the fix mechanical:

1. `ts_ns` range → two binary searches on the sorted `ts` vector → one
   contiguous hyperslab. `O(log T + result)` instead of 493 476 rows.
2. `series_id` membership → index lookup in the sorted `series_id` vector → row
   selection on `values`; HDF5 reads only the intersecting chunks.
3. `split(start, length)` becomes a **chunk-range** split, which is why chunking
   is `(S, 3600)` — one chunk per series-hour, so splits are alignment-free.
4. Above the reader: Iceberg manifest metrics (lower/upper bounds on `ts_ns`,
   `series_id`) let the planner skip whole files before opening them.
   **Confirmed missing.** `IcebergHdf5Register.java:106` builds the `DataFile`
   with path / format / size / recordCount / partition and **no
   `withMetrics(...)`**. So today only *partition* pruning works
   (`epoch_hour = X`); a `ts_ns` range predicate cannot skip a single file. The
   settle writer must emit `Metrics` with `ts_ns` and `series_id` bounds — that
   is a second, independent half of the predicate fix, above the reader.

## Migration

Kudu metrics are zeroed and rebuilt (authorised). Tier1 history is kept.

1. Generalise the C++ creator (`gpu_kudu_create.cc` → `signals_kudu_create.cc`).
   **Never HS2.**
2. Create `signal_tier0`, `latent_tier0`; pre-provision range bounds ahead of
   the write head so the 1 Hz writer never stalls at a boundary.
3. Repoint `warehouse_ingest` (still parked at `87c279b`); unpark the DCGM and
   cognition captures onto `signal_tier0`.
3b. Set `--array_cell_max_elem_num` (4096 for latents; higher only if a ColBERT
   design demands it). Leave `max_cell_size_bytes` alone — it is unsafe-tagged.
4. Drop `gpu_metrics_tier0`. Leave `gpu_metrics_tier1` in place as legacy —
   493 476 settled rows, incompatible layout, but it is history and dropping it
   is not required by anything here.
5. Generalise the tier1 writer + `probe_metric_group` to the schema above,
   behind `@schema_version`, so the reader can carry both.
6. Extend tier-up/settle (`gpu_metrics_settle` covers only `gpu_metrics`) to the
   new products **before** they take writes.
7. Implement decimal predicate pushdown in `kudu_pred.c` — **before** `val`
   becomes decimal.
8. Only then: implement `filter()` / `split()`.

## Open items

- Array columns: encoding/compression accepted by the builder, but block-size
  tuning for 3 KB cells is unmeasured.
- `SERIAL` (non-unique PK + auto-increment) would remove the explicit `seq`.
  Deferred: explicit `seq` is deterministic and its FDW mapping is already
  proven (`SERIAL → bigint`).
