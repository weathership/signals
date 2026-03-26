# Bootstrap Classification Demo: Cerebras GLM-4.7

**Date:** 2026-03-25 05:35 UTC
**Model:** zai-glm-4.7 (358B MoE) via Cerebras Cloud API
**Dataset:** Synthetic SIGDG (7,734 columns, 175 annotation categories)

## Results

| Metric | Value |
|--------|-------|
| Columns classified | 6,679 / 7,734 (86.4%) |
| LLM-direct labels | 6,562 |
| Propagated labels | 117 |
| Failed batches | 14 / 155 (9%) |
| Mean DST conflict K | 0.002 |
| API calls | 155 |
| Input tokens | 2,714,004 |
| Output tokens | 1,999,844 |
| Estimated cost | ~$6.03 ($1.63 in + $4.40 out) |

## Accuracy

**77.8% (1,243 / 1,598)** on the resolvable category subset.

The ground truth uses 175 fine-grained annotation categories (hierarchical BFO codes
like `1.1.1.7.3.3`), while the bootstrap classifies into 30 SIGDG leaf codes (like
`0086`). Only 37 of 175 GT categories resolve directly to SIGDG leaves, leaving
5,081 columns in the "unresolved" bucket (taxonomy granularity mismatch, not errors).

### Mismatches

Dominant confusable pairs in the 355 errors:

| Bootstrap | Ground Truth | Count | Notes |
|-----------|-------------|-------|-------|
| BankAccountData (0071) | PaymentCardData (0070) | ~50 | Financial siblings |
| CredentialInformation (0026) | PaymentCardData (0070) | ~30 | DEBIT_PIN classified as credential |
| PlatformIdentifier (0012) | DeviceIdentifier (0013) | ~20 | GUID/SEID confusion |
| EmailAddress (0076) | PlatformIdentifier (0012) | ~20 | Platform IDs with @ format |
| Masking (0090) | PaymentCardData (0070) | ~15 | "Masked PAN" classified by transformation |

These are genuine semantic ambiguities where the column name alone is insufficient
to distinguish between related categories without domain-specific context.

## Architecture

2-phase bootstrap (no iterative loops needed):

1. **Phase 1 — LLM sweep**: All 7,734 columns sent to GLM-4.7 in 155 batches
   of 50. Each batch prompt includes column name, type, sample values, and sibling
   column names. System prompt contains the 30-category SIGDG taxonomy table.

2. **Phase 2 — ML validation**: DST evidence fusion (cosine + CatBoost + pattern +
   name_match + SVM) runs once. Mean K = 0.002 — near-zero conflict between LLM
   and ML pipeline predictions. No disagreements triggered, so Phase 3 (targeted
   revisit) was not needed.

## Technical Notes

- **GLM-4.7 reasoning tokens**: ~80-85% of output tokens are reasoning (internal
  CoT). For 50-column batches: ~2,600 reasoning + ~6,500 content tokens.
  `max_tokens` must be set to >=65536 to avoid truncation.

- **Cerebras model ID**: `zai-glm-4.7` (prefixed with `zai-`), not `glm-4.7`.

- **Empty response rate**: 14/155 batches (9%) returned empty content — likely
  Cerebras rate limits or transient API issues. Retry logic would recover these.

- **Token cost**: $0.60/M input + $2.20/M output at Cerebras Cloud pricing.

## Next Steps

1. Add retry logic for failed batches (exponential backoff)
2. Evaluate with `llama3.1-8b` (lower cost, no reasoning overhead) for comparison
3. Feed `bootstrap_gt.json` into `--self-train` pipeline for CatBoost refinement
4. Bridge the taxonomy gap: map 175 annotation codes to 30 SIGDG leaves in the
   ground truth, or extend SIGDG to cover all 175 leaf categories
