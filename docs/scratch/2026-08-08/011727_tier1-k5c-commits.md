# Tier-1 green + K5c commits (2026-08-08)

## 1. Tier-1 meta-tagging
With RAID HF caches (`HF_HOME`, `SENTENCE_TRANSFORMERS_HOME`, `HF_HUB_OFFLINE=1`):
**6 scenarios passed** including Tagger dry-run.

## 2. Commits
| Repo | Commit | Summary |
|------|--------|---------|
| impala_fdw | `73e7e4c` | K5b/K5c SASL client + EXPLAIN Auth/Principal |
| signals | `c83400e` | rdbms_* cutover, HF RAID, fdw pin |
| signals | `83e508f` | Kudu SPN pin + kudu_kerberos_fdw_smoke.sh |

## 3. K5c status
- EXPLAIN: `Impala Auth` + `Impala Principal` (e.g. kerberos → `rch@DEV.VISTA.ZNDX.ORG`)
- log_path_choice includes auth/principal
- MODE=1 live: needs stack restart with `SIGNALS_KUDU_KERBEROS=1`
  - Bug fixed: `kudu/_HOST` → `tinybox.lan` vs keytab `kudu/tinybox.dev.vista.zndx.org`
  - Now: `--principal=kudu/$SIGNALS_KRB_HOST`
  - Smoke: `SIGNALS_KUDU_KERBEROS=1 bash scripts/kudu_kerberos_fdw_smoke.sh`

## Next (user plan)
SDG S0 samples after Metabase thinking + Aegir row deepening.
