# Finalized schemas E2E: PostgreSQL → Kudu → HDF5/Iceberg

Guru: `#SL.00000027.SCHEMA2`
Supersedes the exploratory draft in `195942_two-tier-schema-redesign.md`.

## 0. The typing rule

> **INT in → INT out, same precision.** Handed an integer, persist an integer of
> the same width. Never widen to float.
>
> **Float in → DECIMAL considered.** Handed a genuine float, use DECIMAL where
> our own processing would otherwise accumulate IEEE artifacts.
>
> **Model-derived vectors stay FLOAT.** Latents, activations, logits and
> embeddings are natively float and are consumed in float by Ripser, ORC and
> MaxSim. Round-tripping them through decimal adds two conversions and buys
> nothing.

The third clause is why decimal stops at the telemetry boundary. A vector that
leaves storage for `ripser` is not made more exact by being stored as decimal —
it is made *less* direct.

### This is broken at ingest today, not only in storage

`warehouse_ingest.py:83-91` calls `float(val)` on **every** DCGM field:

```python
if metric == "DCGM_FI_DEV_POWER_USAGE":   rec["power_w"]     = float(val)
elif metric == "DCGM_FI_DEV_GPU_UTIL":    rec["util_pct"]    = float(val)   # integer %
elif metric == "DCGM_FI_DEV_FB_USED":     rec["mem_used_mb"] = float(val)   # integer MiB
elif metric == "DCGM_FI_DEV_GPU_TEMP":    rec["temp_c"]      = float(val)   # integer °C
elif metric in _DCGM_EXTRA:               rec[...]           = float(val)   # incl. energy_mj
```

DCGM emits these as integers. The widening happens in our parser, before Kudu
ever sees them. **Fixing the schema without fixing the parser fixes nothing.**

### Native types of the 17 DCGM families

| Field | Native | Stored |
|---|---|---|
| `SM_CLOCK`, `MEM_CLOCK` | int MHz | `INT32` |
| `GPU_TEMP`, `MEMORY_TEMP` | int °C | `INT32` |
| `GPU_UTIL`, `MEM_COPY_UTIL`, `ENC_UTIL`, `DEC_UTIL` | int % | `INT32` |
| `FB_FREE`, `FB_USED` | int MiB | `INT64` |
| `TOTAL_ENERGY_CONSUMPTION` | int mJ | `INT64` |
| `XID_ERRORS`, `*_REMAPPED_ROWS`, `ROW_REMAP_FAILURE` | int | `INT64` |
| `NVLINK_BANDWIDTH_TOTAL` | int | `INT64` |
| `POWER_USAGE` | **double** W | `DECIMAL(18,6)` |

**16 of 17 are integers.** Only `POWER_USAGE` is genuinely float — and even
there the NVML source is integer milliwatts, so `power_mw INT32` would be exact.
Offered as an option; DECIMAL watts is the conservative default because it is
what the exporter actually hands us.

vLLM: counters and queue depths are integers (`INT64`) despite Prometheus text
rendering them `3.0`; ratios and latency histograms are genuine floats
(`DECIMAL(18,6)`). The per-series declaration in §2 is what decides the parse.

---

## 1. Roster and tablet budget

**Reference — Kudu only, never tiers.** Small, permanent, point-queried.

| Table | Rows | Hash | Range | Tablets |
|---|---|---|---|---|
| `signal_series` | ~150 | 2 | none | 2 |
| `clt_feature` | 573 440 | 2 | none | 2 |
| `clt_label` | grows slowly | 2 | none | 2 |

**Time series — Kudu tier0 → HDF5/Iceberg tier1.**

| Table | Hash | Range (day-wide, 3 hot) | Tablets |
|---|---|---|---|
| `signal_tier0` | 4 | 3 | 12 |
| `latent_tier0` | 2 | 3 | 6 |
| `clt_activation_tier0` | 4 | 3 | 12 |

**Deferred:** `embedding_tier0` — not created until the ColBERT packing
benchmark concludes (see `195942_…#colbert-zero-packing`).

**Total: 36 tablets**, against 42 for today's single `gpu_metrics_tier0`.

---

## 2. `signal_series` — the series registry (reference)

The registry is what makes one narrow table hold mixed-typed metrics: it
declares each series' storage type and canonical unit, and the ingest parser
routes on it.

### Kudu

```
series_id   INT64   NOT NULL  BIT_SHUFFLE   PK   -- hash64(name)
name        STRING  NOT NULL  DICT               -- 'dcgm.gpu_util'
vtype       INT8    NOT NULL  RLE                -- 0=int 1=decimal
unit        STRING  NOT NULL  DICT               -- 'percent','MiB','mJ','W','s'
src         INT8    NOT NULL  RLE                -- 0=dcgm 1=vllm 2=engine 3=host
dcgm_field  STRING  NULL      DICT               -- 'DCGM_FI_DEV_GPU_UTIL'
description STRING  NULL      PLAIN
PRIMARY KEY (series_id)
HASH (series_id) 2 BUCKETS
```

### PostgreSQL

```sql
CREATE FOREIGN TABLE signal_series (
  series_id   bigint,  name        text,
  vtype       smallint, unit       text,
  src         smallint, dcgm_field text,
  description text
) SERVER impala OPTIONS (table 'signal_series', am 'kudu_scan');
```

No tier1. Reference data does not settle.

---

## 3. `signal_tier0` / `signal_tier1` — scalar telemetry

Two typed value columns, exactly one non-NULL per row, discriminated by the
series' `vtype`. Kudu is columnar, so the unused column costs a null-bitmap bit
and a query over integer series never reads the decimal column at all.

### Kudu (tier0)

```
epoch_hour  INT32          NOT NULL  RLE          PK
ts_ns       INT64          NOT NULL  BIT_SHUFFLE  PK
series_id   INT64          NOT NULL  BIT_SHUFFLE  PK
src         INT8           NOT NULL  RLE
gpu         INT8           NULL      RLE
inst        INT16          NULL      RLE
val_i       INT64          NULL      BIT_SHUFFLE  -- integer sources
val_d       DECIMAL(18,6)  NULL      BIT_SHUFFLE  -- genuine floats
PRIMARY KEY (epoch_hour, ts_ns, series_id)
HASH (series_id) 4 BUCKETS
RANGE (epoch_hour) day-wide bounds, 3 hot
COMPRESSION LZ4 throughout
```

`series` name is **not** denormalised onto the row — it lives in
`signal_series`. Dropping it costs a join the FDW pushes as a small hash and
saves rewriting ~150 dictionary entries 432 000 times an hour.

Hash on `series_id`, not time: a monotonic `ts_ns` alone would drive every write
into one tablet's tail, the first hot-spot the Kudu schema guide names.

`DECIMAL(18,6)` = 12 digits before the point. Requires **canonical SI units
normalised at ingest** — energy in mJ at 1500 W would exhaust ±10¹² in 7.7 days;
`unit` in `signal_series` is what makes that decidable and auditable.

### PostgreSQL

```sql
CREATE FOREIGN TABLE signal_tier0 (
  epoch_hour integer, ts_ns bigint, series_id bigint,
  src smallint, gpu smallint, inst smallint,
  val_i bigint, val_d numeric(18,6)
) SERVER impala OPTIONS (table 'signal_tier0', am 'kudu_scan');

CREATE FOREIGN TABLE signal_tier1 (   -- same shape, Iceberg
  epoch_hour integer, ts_ns bigint, series_id bigint,
  src smallint, gpu smallint, inst smallint,
  val_i bigint, val_d numeric(18,6)
) SERVER impala OPTIONS (table 'signal_tier1', am 'impala_sql');

CREATE VIEW signal AS
  SELECT * FROM signal_tier0 UNION ALL SELECT * FROM signal_tier1;
```

Schema-identical by construction — the precondition for the union view being
trustworthy, and the reason quantisation was rejected in §0.

### Iceberg

```
epoch_hour int, ts_ns long, series_id long,
src int, gpu int, inst int,
val_i long, val_d decimal(18,6)
PARTITIONED BY identity(epoch_hour)
TBLPROPERTIES ('write.format.default' = 'hdf5')
```

### HDF5

Split by `vtype` so each matrix is dense rather than half-NULL:

```
/signal/int
  ts         int64 [T]        sorted, unique          ← predicate index
  series_id  int64 [Si]       sorted                  ← predicate index
  values     int64 [Si][T]    chunked (Si, 3600), shuffle+gzip
  present    uint8 [Si][T]
/signal/dec
  ts         int64 [T]
  series_id  int64 [Sd]
  values     int64 [Sd][T]    UNSCALED, @scale = 6
  present    uint8 [Sd][T]
@ts_min @ts_max @schema_version = 2
```

**Decimal is stored as its unscaled integer plus a `@scale` attribute — exactly
how Kudu represents it internally**, so the tiers match bit for bit rather than
merely numerically. HDF5 has no decimal type and needs none.

Integer datasets also compress better than float here: HDF5's shuffle filter
groups like-significance bytes, and slowly-varying fixed-point telemetry has
near-constant high bytes that gzip crushes. Float mantissa low bits are noise.
Honouring the source types makes tier1 *smaller*.

`present` states gaps rather than imputing them — no fabricated samples.

---

## 4. `latent_tier0` / `_tier1` — LatentMAS thoughts and KV

Qwen3-1.7B-Base: `hidden_size` 2048, 28 layers, GQA 16 Q × 128 / 8 KV × 128. A
latent thought is the last-layer hidden state (**2048**); transferred KV is
**1024** per side per layer.

FLOAT throughout — these go to Ripser and ORC in float.

### Kudu (tier0)

```
epoch_hour  INT32    NOT NULL  RLE          PK
ts_ns       INT64    NOT NULL  BIT_SHUFFLE  PK
stream_id   INT64    NOT NULL  BIT_SHUFFLE  PK   hash(agent, stream)
seq         INT32    NOT NULL  RLE          PK   row ordinal within instant
kind        INT8     NOT NULL  RLE               0=thought 1=kv
step        INT32    NOT NULL  RLE               latent step
layer       INT16    NULL      RLE               0..27, kv only
norm        FLOAT    NULL      BIT_SHUFFLE
agent       STRING   NOT NULL  DICT
model       STRING   NOT NULL  DICT              'Qwen/Qwen3-1.7B-Base'
ref         STRING   NULL      DICT              task/trace id
vec         FLOAT[]  NULL      LZ4               thought, 2048
k_vec       FLOAT[]  NULL      LZ4               GQA K, 1024
v_vec       FLOAT[]  NULL      LZ4               GQA V, 1024
PRIMARY KEY (epoch_hour, ts_ns, stream_id, seq)
HASH (stream_id) 2 BUCKETS · RANGE (epoch_hour) day-wide, 3 hot
```

⚠ **Requires `--array_cell_max_elem_num=4096`.** The default is **1024**
(`row_operations.cc:56`), which a single 2048-d thought already exceeds. The
flag is tunable and not unsafe-tagged; `row_operations-test.cc:1159` exercises
64 K. Set it **before** first write.

Byte-wise all three arrays are fine: 8 KB, 4 KB, 4 KB against the 64 KB cap.
KV decomposes by `layer` — 28 rows per step at 8 KB — which the 4-column PK
absorbs unchanged because `seq` is the row ordinal within the instant.

**KV is a cache, not ground truth.** A thought is 8 KB; its KV is 224 KB, 28×
more — the paper's `d_h × L` term exactly. Thought sequence + `model` is the
irreducible record and KV is recomputable by replay. Capture thoughts always,
KV by opt-in or sampling.

### PostgreSQL

```sql
CREATE FOREIGN TABLE latent_tier0 (
  epoch_hour integer, ts_ns bigint, stream_id bigint, seq integer,
  kind smallint, step integer, layer smallint, norm real,
  agent text, model text, ref text,
  vec real[], k_vec real[], v_vec real[]
) SERVER impala OPTIONS (table 'latent_tier0', am 'kudu_scan');
```

⚠ Arrays are **payload-only**: Kudu cannot predicate them. Every filterable
dimension above is a scalar column, and `norm` exists solely so magnitude is
queryable without materialising `vec`.

### HDF5

Fixed-shape groups — HDF5's strength, and no offset index needed:

```
/latent/thought
  ts int64[N], stream_id int64[N], step int32[N], norm float32[N]
  vec float32 [N][2048]   chunked (64, 2048), gzip
/latent/kv
  ts int64[M], stream_id int64[M], step int32[M], layer int16[M]
  k   float32 [M][1024]   chunked (64, 1024)
  v   float32 [M][1024]
@ts_min @ts_max @hidden_size = 2048 @kv_width = 1024 @layers = 28
```

---

## 5. CLT interpretability

**Features are stable; labels drift.** The retrieval requirement — reconstruct
how an agent labelled a text→activation event in a past timeframe — makes this
bitemporal, not a storage-size problem.

### 5a. `clt_feature` (reference, never tiers)

```
model_id     INT32    NOT NULL  RLE          PK   hash('clt-qwen3-1.7b-base-20k')
layer        INT16    NOT NULL  RLE          PK   0..27
feature_idx  INT32    NOT NULL  BIT_SHUFFLE  PK   0..20479
top_token_id INT32[]  NOT NULL  LZ4               top-k promoted tokens
top_logit    FLOAT[]  NOT NULL  LZ4               model output → FLOAT
decoder_norm FLOAT    NULL      BIT_SHUFFLE
PRIMARY KEY (model_id, layer, feature_idx)
HASH (feature_idx) 2 BUCKETS
```

28 × 20 480 = 573 440 rows, written once per CLT model. At k=32 the arrays are
64 elements / ~256 B — inside both caps at their defaults.

### 5b. `clt_label` (reference, append-only, bitemporal)

```
model_id      INT32   NOT NULL  RLE          PK
layer         INT16   NOT NULL  RLE          PK
feature_idx   INT32   NOT NULL  BIT_SHUFFLE  PK
valid_from_ns INT64   NOT NULL  BIT_SHUFFLE  PK   ← anti-overwrite guard
label         STRING  NOT NULL  DICT
agent         STRING  NOT NULL  DICT
confidence    FLOAT   NULL      BIT_SHUFFLE
evidence_ref  STRING  NULL      DICT
supersedes_ns INT64   NULL      BIT_SHUFFLE
PRIMARY KEY (model_id, layer, feature_idx, valid_from_ns)
HASH (feature_idx) 2 BUCKETS
```

⚠ **Kudu UPSERT is the hazard.** Overwriting a label is precisely the operation
that destroys the history this table exists to hold. `valid_from_ns` is in the
PK so a re-label is a new row and cannot collide. **INSERT only — there is no
UPDATE path.** As-of-T is the newest row with `valid_from_ns <= T`.

Feature-major PK order makes "every label this feature ever carried" one
contiguous scan, with as-of-T a range predicate on that scan.

### 5c. `clt_activation_tier0` / `_tier1` (time series)

```
epoch_hour INT32    NOT NULL  RLE          PK
ts_ns      INT64    NOT NULL  BIT_SHUFFLE  PK
text_id    INT64    NOT NULL  BIT_SHUFFLE  PK   hash of the text item
pos        INT32    NOT NULL  RLE          PK   token position
layer      INT16    NOT NULL  RLE          PK
feat_idx   INT32[]  NOT NULL  LZ4               top-k active indices
feat_val   FLOAT[]  NOT NULL  LZ4               activations → FLOAT
nnz        INT32    NOT NULL  BIT_SHUFFLE
agent      STRING   NULL      DICT
ref        STRING   NULL      DICT
PRIMARY KEY (epoch_hour, ts_ns, text_id, pos, layer)
HASH (text_id) 4 BUCKETS · RANGE (epoch_hour) day-wide, 3 hot
```

Sparse pairs at L0≈115 are 230 elements / ~920 B — inside both caps at their
defaults, and 115× fewer rows than one row per active feature. This is *sparse*,
not full-vector: the dense alternative is 20 480 floats = 80 KB, over the byte
cap and 20× over the element cap.

`nnz` is scalar because arrays cannot be predicated.

### HDF5 for 5c

`CLT_L0_SPARSITY` is a **top-k** parameter (`clt_memory.py:328`), so `nnz` is
constant and the payload is a **fixed** `[N][K]` matrix — no ragged VLEN needed:

```
/clt/act
  ts int64[N], text_id int64[N], pos int32[N], layer int16[N]
  feat_idx float32→int32 [N][115]   chunked (256, 115)
  feat_val float32       [N][115]
@ts_min @ts_max @k = 115 @model_id
```

### The query this exists to serve

> As of last Tuesday, how did the agent label the features that fired on this text?

```sql
SELECT a.text_id, a.pos, a.feat_idx, a.feat_val, l.label, l.agent
FROM clt_activation_tier0 a
CROSS JOIN LATERAL (
  SELECT label, agent FROM clt_label
   WHERE feature_idx = <f> AND valid_from_ns <= a.ts_ns
   ORDER BY valid_from_ns DESC LIMIT 1
) l
WHERE a.epoch_hour BETWEEN <lo> AND <hi>;
```

`epoch_hour`/`ts_ns` prune partitions on the event side; `feature_idx` is a PK
prefix lookup on the label side. Neither touches an array.

---

## 6. Migration sequence

Ordering is load-bearing — several steps are prerequisites, not preferences.

1. **`kudu_pred.c`: decimal predicate pushdown.** No decimal handling exists
   today. Without it `WHERE val_d > x` degrades to a local filter — the same
   regression class as the parameterised-predicate bug (12.92 s → 0.01 s).
   **Must land before `val_d` carries data.**
2. **`warehouse_ingest.py`: stop widening.** Parse per `signal_series.vtype`;
   integers to `int`, floats to `Decimal`. Map DCGM "unavailable" to explicit
   NULL — decimal has no NaN, and NaN silently poisons aggregates anyway.
3. **Set `--array_cell_max_elem_num=4096`** on the tservers. Leave
   `max_cell_size_bytes` alone — it is `TAG_FLAG(unsafe)`.
4. **Generalise the creator** `gpu_kudu_create.cc` → `signals_kudu_create.cc`.
   **Never HS2** — that path SIGSEGV'd the tserver 415 times on 2026-08-24.
5. Create the six tables; pre-provision range bounds ahead of the write head so
   the 1 Hz writer never stalls at a boundary.
6. Seed `signal_series` and `clt_feature` before any time-series write.
7. Drop `gpu_metrics_tier0`. Leave `gpu_metrics_tier1` as legacy — 493 476
   settled rows in an incompatible layout, but it is history.
8. Generalise the tier1 writer: schema-driven, **no int16 quantisation**
   (`generate_sdg_hdf5.py:157` currently forces `dtype=np.int16` and clips at
   `:224-235`; an 80 GB card's `FB_USED` = 81 920 silently becomes 32 767).
9. Add `Metrics` to `IcebergHdf5Register.java:106` — `withMetrics(...)` is absent,
   so only partition pruning works today and a `ts_ns` range predicate cannot
   skip a single file.
10. Extend tier-up/settle to all three time-series products **before** they take
    writes (`gpu_metrics_settle` covers only `gpu_metrics`).
11. **Only then:** `Hdf5ReadBuilder.filter()` / `.split()`.

## 7. Open

- ColBERT packing benchmark → then `embedding_tier0`.
- `POWER_USAGE` as `power_mw INT32` (exact, NVML-native) vs `DECIMAL(18,6)` W.
- Array block-size tuning for 8 KB cells is unmeasured.
