#!/usr/bin/env bash
# just backup — the only backup path.
#
# Full-stack, portable, fail-closed. Every service is backed up the same way
# every time:
#   • Postgres SoRs (Atlas/signals, Ranger, catalog, polaris if present) → pg_dump
#   • Kudu tables → logical Parquet via Impala + DataFusion (signals-df)
#   • rustfs / flink data dirs under SIGNALS_DATA_ROOT → sibling tars
#   • DataFusion verifies the logical plane before success
#
# There is no service subset, no Kudu skip/physical mode, and no "partial OK".
# If anything cannot be backed up properly, exit 1.
#
# Usage:  just backup
#         just backup --stamp 20260808T120000Z   # optional fixed stamp name
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/signals_data_root.sh
source "$ROOT/scripts/signals_data_root.sh"
# shellcheck source=scripts/signals_df.sh
source "$ROOT/scripts/signals_df.sh"
# shellcheck source=scripts/signals_kerberos.sh
source "$ROOT/scripts/signals_kerberos.sh"
signals_ensure_data_layout
signals_krb_env "$ROOT"

PGHOST="${PGHOST:-127.0.0.1}"
PGPORT="${PGPORT:-5455}"
PGUSER="${PGUSER:-${USER:-signals}}"
# Kerberos: always dial FQDN (SPN impala/$SIGNALS_KRB_HOST) — never 127.0.0.1
IMPALA_HS2_HOST="${IMPALA_HS2_HOST:-$SIGNALS_KRB_HOST}"
IMPALA_HS2_PORT="${IMPALA_HS2_PORT:-21050}"
STAMP="${SIGNALS_BACKUP_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
OUT="${SIGNALS_BACKUP_DIR}/${STAMP}"

impala_q() {
  # Kerberos GSSAPI via impyla (reliable; avoids broken impala-shell thrift/GSS)
  uv run python "$ROOT/scripts/impala_query.py" "$@"
}

ERRORS=()
OK=()
WARNINGS=()

fail() { ERRORS+=("$*"); echo "ERROR: $*" >&2; }
ok()   { OK+=("$*"); echo "  ok: $*"; }
warn() { WARNINGS+=("$*"); echo "  warn: $*" >&2; }

usage() {
  cat <<EOF
Usage: $(basename "$0") [--stamp STAMP]

  The only path: full portable backup of all Signals services.

  --stamp STAMP   Directory name under \$SIGNALS_BACKUP_DIR (default: UTC now)

Requires: devenv stack up (Postgres, Kudu, Impala HS2), cargo/signals-df for Kudu.

Exit 0 only when every service is backed up and verified.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --stamp) STAMP="${2:-}"; OUT="${SIGNALS_BACKUP_DIR}/${STAMP}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    --services)
      echo "ERROR: --services is not supported. just backup always backs up all services." >&2
      echo "  There is one portable path — not a menu of subsets." >&2
      exit 2
      ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

mkdir -p "$OUT"/{postgres,ranger-conf,filesystem,logical}
echo "signals backup (full portable path) → $OUT"
echo "  SIGNALS_DATA_ROOT=$SIGNALS_DATA_ROOT"

# ── DataFusion (required — logical plane for Kudu and stamp verify) ─
DF_BIN=""
if ! DF_BIN=$(signals_df_ensure "$ROOT"); then
  fail "signals-df unavailable — full backup requires DataFusion (cargo build -p signals-df)"
else
  ok "signals-df ready ($DF_BIN)"
  if ! "$DF_BIN" init --stamp "$OUT"; then
    fail "signals-df init failed"
  fi
fi

pg_ready() {
  command -v pg_isready >/dev/null 2>&1 \
    && pg_isready -h "$PGHOST" -p "$PGPORT" -q 2>/dev/null
}

db_exists() {
  local db="$1"
  psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname='${db}'" 2>/dev/null | grep -q 1
}

dump_db() {
  local db="$1"
  local label="${2:-$db}"
  local dest="$OUT/postgres/${db}.dump"
  local sql="$OUT/postgres/${db}.sql"

  if ! db_exists "$db"; then
    fail "$label: database '$db' does not exist on ${PGHOST}:${PGPORT}"
    return 1
  fi

  echo "  pg_dump $db → $dest"
  if ! PGPASSWORD="${PGPASSWORD:-}" pg_dump \
      -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" \
      -Fc --no-owner --no-acl -f "$dest" "$db"; then
    fail "$label: pg_dump -Fc failed for '$db'"
    return 1
  fi
  if [ ! -s "$dest" ]; then
    fail "$label: dump empty: $dest"
    return 1
  fi
  if ! PGPASSWORD="${PGPASSWORD:-}" pg_dump \
      -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" \
      --no-owner --no-acl -f "$sql" "$db"; then
    fail "$label: pg_dump SQL failed for '$db'"
    return 1
  fi
  if [ ! -s "$sql" ]; then
    fail "$label: SQL dump empty: $sql"
    return 1
  fi
  ok "$label ($db.dump + $db.sql, $(du -h "$dest" | awk '{print $1}'))"
}

tar_dir() {
  local name="$1" src="$2" label="${3:-$1}"
  local dest="$OUT/filesystem/${name}.tgz"

  if [ ! -d "$src" ]; then
    fail "$label: data directory missing: $src (run signals:data-layout / devenv up)"
    return 1
  fi
  if [ -z "$(ls -A "$src" 2>/dev/null)" ]; then
    echo "empty" > "$OUT/filesystem/${name}.EMPTY"
    ok "$label: empty tree at $src (recorded ${name}.EMPTY)"
    return 0
  fi
  echo "  tar $name ← $src"
  if ! tar -C "$(dirname "$src")" -czf "$dest" "$(basename "$src")"; then
    fail "$label: tar failed for $src"
    return 1
  fi
  if [ ! -s "$dest" ]; then
    fail "$label: archive empty: $dest"
    return 1
  fi
  ok "$label ($(du -h "$dest" | awk '{print $1}') → ${name}.tgz)"
}

kudu_live() {
  curl -sf -o /dev/null --connect-timeout 2 "http://127.0.0.1:8051/" 2>/dev/null \
    || curl -sf -o /dev/null --connect-timeout 2 "http://127.0.0.1:8050/" 2>/dev/null
}

# ── Postgres SoRs (always) ─────────────────────────────────────────
if ! command -v pg_dump >/dev/null 2>&1; then
  fail "postgres: pg_dump not on PATH (enter devenv shell)"
elif ! pg_ready; then
  fail "postgres: not ready at ${PGHOST}:${PGPORT} — run 'devenv up -d' then just backup"
else
  dump_db signals "atlas (signals DB / AGE SoR)" || true
  dump_db ranger "ranger" || true
  dump_db signals_catalog "catalog (signals_catalog)" || true
  if db_exists polaris; then
    dump_db polaris "polaris" || true
  else
    echo "absent" > "$OUT/postgres/polaris.ABSENT"
    ok "polaris: database not present (recorded ABSENT — stack without Polaris)"
  fi
  echo "  pg_dumpall --roles-only"
  if pg_dumpall -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" --roles-only \
      > "$OUT/postgres/roles.sql" 2>/dev/null \
      && [ -s "$OUT/postgres/roles.sql" ]; then
    ok "postgres roles (roles.sql)"
  else
    fail "postgres: pg_dumpall --roles-only failed or empty"
  fi
fi

# ── Ranger conf (always attempt; DB is authoritative if conf missing) ─
RHOME="$ROOT/.devenv/ranger"
if [ -d "$RHOME/admin/ews/webapp/WEB-INF/classes/conf" ]; then
  mkdir -p "$OUT/ranger-conf"
  if tar -C "$RHOME/admin/ews/webapp/WEB-INF/classes" -czf \
      "$OUT/ranger-conf/conf.tgz" conf \
      && [ -s "$OUT/ranger-conf/conf.tgz" ]; then
    ok "ranger-conf (conf.tgz)"
  else
    fail "ranger-conf: failed to archive conf"
  fi
  if [ -f "$RHOME/admin/install.properties" ]; then
    cp -a "$RHOME/admin/install.properties" "$OUT/ranger-conf/" || \
      fail "ranger-conf: could not copy install.properties"
  fi
else
  echo "not-installed" > "$OUT/ranger-conf/NOT_INSTALLED"
  ok "ranger-conf: not installed (NOT_INSTALLED; ranger DB dump is SoR)"
fi

# ── Kudu logical (always — portable Parquet only) ──────────────────
export_kudu_table() {
  local table="$1"
  local tmp csv
  tmp=$(mktemp -d)
  csv="$tmp/${table//./_}.csv"
  echo "  kudu export (GSSAPI): $table"
  if ! impala_q -q "SELECT * FROM ${table}" -o "$csv" --header 2>"$tmp/err"; then
    fail "kudu: Impala GSSAPI export failed for $table ($(head -3 "$tmp/err" | tr '\n' ' '))"
    rm -rf "$tmp"
    return 1
  fi
  [ -s "$csv" ] || : > "$csv"
  if [ -z "$DF_BIN" ]; then
    fail "kudu: signals-df missing for ingest of $table"
    rm -rf "$tmp"
    return 1
  fi
  if ! "$DF_BIN" ingest --stamp "$OUT" --service kudu --table "${table//./__}" \
      --input "$csv" --delimiter $'\t' --has-header true; then
    fail "kudu: signals-df ingest failed for $table"
    rm -rf "$tmp"
    return 1
  fi
  rm -rf "$tmp"
  ok "kudu: $table → logical/kudu/"
}

# Kerberos ticket required for Impala logical export
if ! signals_krb_ticket_ok "$ROOT"; then
  if ! signals_krb_kinit "$ROOT"; then
    fail "kerberos: no ticket — run: just kinit  (or just kerberos-migrate)"
  fi
fi
if ! signals_krb_hosts_ok "$ROOT"; then
  fail "kerberos: $SIGNALS_KRB_HOST does not resolve — just kerberos-migrate"
fi

if [ -z "$DF_BIN" ]; then
  fail "kudu: signals-df required for the only portable path"
elif ! kudu_live; then
  fail "kudu: master/tserver not reachable — full backup needs running Kudu (devenv up -d)"
elif ! impala_q --probe -q 'SELECT 1' >/dev/null 2>&1; then
  fail "kudu: Impala HS2 GSSAPI not ready at ${IMPALA_HS2_HOST}:${IMPALA_HS2_PORT}"
  fail "kudu: ensure just bootstrap, devenv up -d, just kinit (Kerberos GSSAPI required)"
else
  ok "impala HS2 GSSAPI ok ($IMPALA_HS2_HOST:$IMPALA_HS2_PORT as $SIGNALS_USER_PRINCIPAL)"
  tables=$(impala_q -q "SHOW TABLES" 2>/dev/null | tr -d '\r' | sed '/^$/d' || true)
  if [ -z "${tables// }" ]; then
    mkdir -p "$OUT/logical/kudu"
    echo '{"service":"kudu","tables":[]}' > "$OUT/logical/kudu/tables.json"
    ok "kudu: 0 tables (empty portable logical snapshot)"
  else
    export_errors=0
    while IFS= read -r table; do
      [ -z "$table" ] && continue
      case "$table" in *.*.*) continue ;; esac
      export_kudu_table "$table" || export_errors=$((export_errors + 1))
    done <<< "$tables"
    if [ "$export_errors" -gt 0 ]; then
      fail "kudu: $export_errors table export(s) failed"
    fi
  fi
  if [ -n "$DF_BIN" ] && ! "$DF_BIN" verify --stamp "$OUT"; then
    fail "kudu: DataFusion verify failed after logical export"
  else
    ok "kudu: DataFusion logical verify ok"
  fi
fi

# Never write physical Kudu FS into a portable stamp
if [ -f "$OUT/filesystem/kudu.tgz" ]; then
  rm -f "$OUT/filesystem/kudu.tgz"
  fail "kudu: refused physical FS artifact (not portable)"
fi

# ── rustfs + flink (always under SIGNALS_DATA_ROOT) ────────────────
tar_dir rustfs "$SIGNALS_RUSTFS_DATA_DIR" "rustfs" || true
tar_dir flink "$SIGNALS_FLINK_DATA_DIR" "flink" || true

# ── Manifest ───────────────────────────────────────────────────────
STATUS="ok"
[ ${#ERRORS[@]} -eq 0 ] || STATUS="failed"

{
  echo "{"
  echo "  \"stamp\": \"$STAMP\","
  echo "  \"status\": \"$STATUS\","
  echo "  \"path\": \"full-portable-all-services\","
  echo "  \"created_utc\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\","
  echo "  \"hostname\": \"$(hostname 2>/dev/null || echo unknown)\","
  echo "  \"signals_data_root\": \"$SIGNALS_DATA_ROOT\","
  echo "  \"pg\": {\"host\": \"$PGHOST\", \"port\": $PGPORT, \"user\": \"$PGUSER\"},"
  echo "  \"portable\": true,"
  echo "  \"logical_plane\": \"datafusion-parquet\","
  echo "  \"services\": [\"atlas\",\"ranger\",\"catalog\",\"kudu\",\"rustfs\",\"flink\"],"
  echo "  \"ok_count\": ${#OK[@]},"
  echo "  \"error_count\": ${#ERRORS[@]},"
  echo "  \"warning_count\": ${#WARNINGS[@]}"
  echo "}"
} > "$OUT/MANIFEST.json"

if [ "$STATUS" = "ok" ] && [ -n "$DF_BIN" ]; then
  if ! "$DF_BIN" verify --stamp "$OUT"; then
    fail "signals-df final verify failed"
    STATUS="failed"
  else
    ok "signals-df final verify ok"
  fi
fi

if [ "$STATUS" = "ok" ] && command -v sha256sum >/dev/null 2>&1; then
  (cd "$OUT" && find . -type f ! -name 'SHA256SUMS' -print0 | sort -z | xargs -0 sha256sum) \
    > "$OUT/SHA256SUMS" || fail "SHA256SUMS generation failed"
  [ -s "$OUT/SHA256SUMS" ] && ok "SHA256SUMS written" || fail "SHA256SUMS empty"
fi

# Recompute status after final checks
[ ${#ERRORS[@]} -eq 0 ] || STATUS="failed"
# rewrite status in manifest if needed
if [ "$STATUS" = "failed" ]; then
  sed -i 's/"status": "ok"/"status": "failed"/' "$OUT/MANIFEST.json" 2>/dev/null || true
fi

echo ""
if [ ${#OK[@]} -gt 0 ]; then
  echo "Succeeded (${#OK[@]}):"
  for m in "${OK[@]}"; do echo "  ✓ $m"; done
fi
if [ ${#WARNINGS[@]} -gt 0 ]; then
  echo "Warnings (${#WARNINGS[@]}):"
  for m in "${WARNINGS[@]}"; do echo "  ! $m"; done
fi

if [ ${#ERRORS[@]} -gt 0 ]; then
  echo "" >&2
  echo "BACKUP FAILED (${#ERRORS[@]} error(s)) — not a complete portable backup" >&2
  echo "Partial artifacts (inspection only): $OUT" >&2
  for m in "${ERRORS[@]}"; do echo "  ✗ $m" >&2; done
  echo "" >&2
  echo "Bring the full stack up (devenv up -d), fix errors, re-run: just backup" >&2
  {
    echo "status=failed"
    printf '%s\n' "${ERRORS[@]}"
  } > "$OUT/FAILED"
  exit 1
fi

echo ""
echo "════════════════════════════════════════════════════════════"
echo " BACKUP VERIFIED — full portable path"
echo "════════════════════════════════════════════════════════════"
echo " Identity"
echo "   stamp:     $STAMP"
echo "   path:      $OUT"
echo "   data_root: $SIGNALS_DATA_ROOT"
echo "   hostname:  $(hostname 2>/dev/null || echo unknown)"
echo "   created:   $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo " Statistics"
if [ -f "$OUT/postgres/signals.dump" ]; then
  echo "   atlas:     $(du -h "$OUT/postgres/signals.dump" | awk '{print $1}')  (signals.dump)"
fi
if [ -f "$OUT/postgres/ranger.dump" ]; then
  echo "   ranger:    $(du -h "$OUT/postgres/ranger.dump" | awk '{print $1}')  (ranger.dump)"
fi
if [ -f "$OUT/postgres/signals_catalog.dump" ]; then
  echo "   catalog:   $(du -h "$OUT/postgres/signals_catalog.dump" | awk '{print $1}')"
fi
if [ -d "$OUT/logical/kudu" ]; then
  kt=$(find "$OUT/logical/kudu" -name '*.parquet' 2>/dev/null | wc -l | tr -d ' ')
  echo "   kudu:      ${kt} parquet table(s) under logical/kudu/"
  if [ -f "$OUT/logical/kudu/tables.json" ] && command -v jq >/dev/null 2>&1; then
    jq -r '.tables[]? | "              \(.name): \(.rows) rows, \(.columns) cols"' \
      "$OUT/logical/kudu/tables.json" 2>/dev/null || true
  fi
fi
if [ -f "$OUT/SHA256SUMS" ]; then
  echo "   checksums: $(wc -l < "$OUT/SHA256SUMS" | tr -d ' ') files in SHA256SUMS"
fi
echo "   ok_steps:  ${#OK[@]}"
echo " Restore with: just restore $STAMP"
echo "════════════════════════════════════════════════════════════"
exit 0
