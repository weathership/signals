#!/usr/bin/env bash
# just restore — the only restore path.
#
# Symmetric to just backup: full-stack, portable, fail-closed.
#   • Refuse FAILED / non-ok / non-portable stamps
#   • Verify SHA256SUMS
#   • Restore all Postgres SoRs + ranger-conf
#   • DataFusion-verify logical/ and stage Kudu Parquet under SIGNALS_DATA_ROOT
#   • Restore rustfs / flink FS siblings
#   • Verify every plane before success
#
# Usage:  just restore <stamp-or-path>
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/signals_data_root.sh
source "$ROOT/scripts/signals_data_root.sh"
# shellcheck source=scripts/signals_df.sh
source "$ROOT/scripts/signals_df.sh"
signals_ensure_data_layout

PGHOST="${PGHOST:-127.0.0.1}"
PGPORT="${PGPORT:-5455}"
PGUSER="${PGUSER:-${USER:-signals}}"
FORCE="${SIGNALS_RESTORE_FORCE:-0}"
SRC=""

ERRORS=()
OK=()
WARNINGS=()

fail() { ERRORS+=("$*"); echo "ERROR: $*" >&2; }
ok()   { OK+=("$*"); echo "  ok: $*"; }
warn() { WARNINGS+=("$*"); echo "  warn: $*" >&2; }

usage() {
  cat <<EOF
Usage: $(basename "$0") <stamp-or-path>

  The only path: full portable restore of a just backup stamp.

  stamp-or-path   Stamp under \$SIGNALS_BACKUP_DIR or absolute path to stamp dir

Requires: Postgres up. Kudu physical FS is never copied between hosts.

Exit 0 only when every service is restored and verified.
EOF
}

if [ $# -lt 1 ]; then usage; exit 2; fi
SRC="$1"; shift
while [ $# -gt 0 ]; do
  case "$1" in
    --services)
      echo "ERROR: --services is not supported. just restore always restores all services." >&2
      exit 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown: $1" >&2; usage; exit 2 ;;
  esac
done

if [ -d "$SRC" ]; then
  BACKUP_DIR="$(cd "$SRC" && pwd)"
elif [ -d "${SIGNALS_BACKUP_DIR}/${SRC}" ]; then
  BACKUP_DIR="$(cd "${SIGNALS_BACKUP_DIR}/${SRC}" && pwd)"
else
  echo "ERROR: backup not found: $SRC" >&2
  echo "  tried ${SIGNALS_BACKUP_DIR}/${SRC}" >&2
  exit 1
fi

echo "signals restore (full portable path) ← $BACKUP_DIR"
echo "  SIGNALS_DATA_ROOT=$SIGNALS_DATA_ROOT"

# ── Gate: complete portable stamp only ─────────────────────────────
if [ -f "$BACKUP_DIR/FAILED" ] && [ "$FORCE" != "1" ]; then
  fail "stamp marked FAILED — refuse restore"
fi
if [ ! -f "$BACKUP_DIR/MANIFEST.json" ]; then
  fail "MANIFEST.json missing — not a just backup stamp"
else
  if command -v jq >/dev/null 2>&1; then
    mstatus=$(jq -r '.status // "unknown"' "$BACKUP_DIR/MANIFEST.json")
    mpath=$(jq -r '.path // empty' "$BACKUP_DIR/MANIFEST.json")
    mport=$(jq -r '.portable // true' "$BACKUP_DIR/MANIFEST.json")
  else
    mstatus=$(sed -n 's/.*"status"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$BACKUP_DIR/MANIFEST.json" | head -1)
    mpath=""; mport=true
  fi
  if [ "$mstatus" != "ok" ] && [ "$FORCE" != "1" ]; then
    fail "MANIFEST status='$mstatus' (need ok)"
  else
    ok "manifest status=${mstatus:-ok}"
  fi
  if [ "$mport" = "false" ]; then
    fail "MANIFEST portable=false — refuse (not a portable stamp)"
  fi
  if [ -n "$mpath" ] && [ "$mpath" != "full-portable-all-services" ] && [ "$mpath" != "null" ]; then
    warn "manifest path='$mpath' (expected full-portable-all-services for new stamps)"
  fi
fi

if [ -f "$BACKUP_DIR/filesystem/kudu.NON_PORTABLE" ] || [ -f "$BACKUP_DIR/filesystem/kudu.tgz" ]; then
  fail "kudu physical FS artifact present — not a valid portable stamp (re-run just backup)"
fi

if [ -f "$BACKUP_DIR/SHA256SUMS" ]; then
  if command -v sha256sum >/dev/null 2>&1; then
    echo "  verifying SHA256SUMS..."
    if (cd "$BACKUP_DIR" && sha256sum -c SHA256SUMS --quiet) 2>/dev/null \
      || (cd "$BACKUP_DIR" && sha256sum -c SHA256SUMS >/dev/null); then
      ok "SHA256SUMS verified"
    else
      fail "SHA256SUMS verification failed"
    fi
  else
    fail "sha256sum not available — cannot verify portable stamp integrity"
  fi
else
  fail "SHA256SUMS missing — incomplete portable stamp"
fi

if [ ${#ERRORS[@]} -gt 0 ]; then
  echo "" >&2
  echo "RESTORE ABORTED before applying changes" >&2
  for m in "${ERRORS[@]}"; do echo "  ✗ $m" >&2; done
  exit 1
fi

pg_ready() {
  command -v pg_isready >/dev/null 2>&1 \
    && pg_isready -h "$PGHOST" -p "$PGPORT" -q 2>/dev/null
}

OUT_RESTORE_LOG="$BACKUP_DIR/restore-logs-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT_RESTORE_LOG"

has_dump() { [ -f "$BACKUP_DIR/postgres/${1}.dump" ] && [ -s "$BACKUP_DIR/postgres/${1}.dump" ]; }

restore_db() {
  local db="$1"
  local label="${2:-$db}"
  local dump="$BACKUP_DIR/postgres/${db}.dump"

  if ! has_dump "$db"; then
    fail "$label: postgres/${db}.dump missing from stamp"
    return 1
  fi
  echo "  pg_restore → $db"
  psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname='${db}'" 2>/dev/null | grep -q 1 \
    || psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres -v ON_ERROR_STOP=1 \
         -c "CREATE DATABASE ${db};"

  psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$db" -v ON_ERROR_STOP=0 <<'SQL' >/dev/null 2>&1 || true
CREATE EXTENSION IF NOT EXISTS age;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pg_cron;
SQL

  set +e
  pg_restore -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" \
    -d "$db" --no-owner --no-acl --clean --if-exists --exit-on-error \
    "$dump" 2>"$OUT_RESTORE_LOG/${db}.pg_restore.log"
  rc=$?
  if [ "$rc" -ne 0 ]; then
    pg_restore -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" \
      -d "$db" --no-owner --no-acl --clean --if-exists \
      "$dump" 2>>"$OUT_RESTORE_LOG/${db}.pg_restore.log"
    rc=$?
  fi
  set -e
  if [ "$rc" -gt 1 ]; then
    fail "$label: pg_restore failed (exit $rc) — see $OUT_RESTORE_LOG/${db}.pg_restore.log"
    return 1
  fi
  if [ "$rc" -eq 1 ]; then
    warn "$label: pg_restore warnings (exit 1) — verifying content"
  fi
  return 0
}

verify_db() {
  local db="$1" label="${2:-$db}" min_tables="${3:-0}"
  if ! psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$db" -c "SELECT 1" >/dev/null 2>&1; then
    fail "$label: cannot connect after restore"
    return 1
  fi
  local n
  n=$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$db" -tAc \
    "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')" \
    2>/dev/null | tr -d '[:space:]')
  if [ "${n:-0}" -lt "$min_tables" ]; then
    fail "$label: expected ≥$min_tables user tables, found ${n:-0}"
    return 1
  fi
  if [ "$db" = "signals" ]; then
    local age
    age=$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$db" -tAc \
      "SELECT count(*) FROM pg_extension WHERE extname='age'" 2>/dev/null | tr -d '[:space:]')
    if [ "${age:-0}" -lt 1 ]; then
      fail "$label: AGE extension missing after restore"
      return 1
    fi
  fi
  ok "$label: verified (${n} user tables)"
}

# ── Postgres ───────────────────────────────────────────────────────
if ! command -v pg_restore >/dev/null 2>&1; then
  fail "postgres: pg_restore not on PATH"
elif ! pg_ready; then
  fail "postgres: not ready at ${PGHOST}:${PGPORT} — devenv up -d then just restore"
else
  restore_db signals "atlas (signals)" || true
  verify_db signals "atlas (signals)" 1 || true
  restore_db ranger "ranger" || true
  verify_db ranger "ranger" 1 || true
  restore_db signals_catalog "catalog" || true
  verify_db signals_catalog "catalog" 0 || true
  if has_dump polaris; then
    restore_db polaris "polaris" || true
    verify_db polaris "polaris" 0 || true
  elif [ -f "$BACKUP_DIR/postgres/polaris.ABSENT" ]; then
    ok "polaris: was absent at backup time"
  else
    fail "polaris: neither dump nor ABSENT marker in stamp"
  fi
fi

# ── Ranger conf ────────────────────────────────────────────────────
if [ -f "$BACKUP_DIR/ranger-conf/conf.tgz" ]; then
  RHOME="$ROOT/.devenv/ranger/admin/ews/webapp/WEB-INF/classes"
  if [ ! -d "$RHOME" ]; then
    fail "ranger-conf: Ranger not installed at $RHOME (ranger:install first)"
  else
    if tar -C "$RHOME" -xzf "$BACKUP_DIR/ranger-conf/conf.tgz"; then
      ok "ranger-conf extracted"
    else
      fail "ranger-conf: extract failed"
    fi
  fi
elif [ -f "$BACKUP_DIR/ranger-conf/NOT_INSTALLED" ]; then
  ok "ranger-conf: NOT_INSTALLED at backup (nothing to extract)"
else
  fail "ranger-conf: missing conf.tgz and NOT_INSTALLED marker"
fi

# ── Kudu logical (always required in portable stamp) ───────────────
if [ ! -d "$BACKUP_DIR/logical/kudu" ]; then
  fail "kudu: logical/kudu missing — stamp is not a full portable backup"
else
  DF_BIN=""
  if ! DF_BIN=$(signals_df_ensure "$ROOT"); then
    fail "kudu: signals-df required to verify logical package"
  elif ! "$DF_BIN" verify --stamp "$BACKUP_DIR"; then
    fail "kudu: DataFusion verify failed"
  else
    ok "kudu: DataFusion logical verify ok"
    mkdir -p "$SIGNALS_DATA_ROOT/logical-restore"
    rm -rf "$SIGNALS_DATA_ROOT/logical-restore/kudu"
    cp -a "$BACKUP_DIR/logical/kudu" "$SIGNALS_DATA_ROOT/logical-restore/"
    if [ ! -d "$SIGNALS_DATA_ROOT/logical-restore/kudu" ]; then
      fail "kudu: failed to stage logical-restore/kudu"
    else
      ok "kudu: staged at $SIGNALS_DATA_ROOT/logical-restore/kudu"
    fi
  fi
fi

# ── rustfs / flink ─────────────────────────────────────────────────
restore_fs() {
  local name="$1" dest="$2" label="${3:-$1}"
  local tgz="$BACKUP_DIR/filesystem/${name}.tgz"
  if [ -f "$BACKUP_DIR/filesystem/${name}.EMPTY" ]; then
    mkdir -p "$dest"
    ok "$label: empty at backup — ensured $dest"
    return 0
  fi
  if [ ! -f "$tgz" ]; then
    fail "$label: filesystem/${name}.tgz and ${name}.EMPTY both missing"
    return 1
  fi
  local parent
  parent="$(dirname "$dest")"
  mkdir -p "$parent"
  if [ -e "$dest" ]; then
    rm -rf "${dest}.bak-restore"
    mv "$dest" "${dest}.bak-restore"
  fi
  if ! tar -C "$parent" -xzf "$tgz"; then
    [ -d "${dest}.bak-restore" ] && mv "${dest}.bak-restore" "$dest"
    fail "$label: tar extract failed"
    return 1
  fi
  rm -rf "${dest}.bak-restore"
  if [ ! -d "$dest" ]; then
    fail "$label: missing after extract: $dest"
    return 1
  fi
  ok "$label: restored to $dest"
}

restore_fs rustfs "$SIGNALS_RUSTFS_DATA_DIR" "rustfs" || true
restore_fs flink "$SIGNALS_FLINK_DATA_DIR" "flink" || true

# ── Summary ────────────────────────────────────────────────────────
STATUS="ok"
[ ${#ERRORS[@]} -eq 0 ] || STATUS="failed"

RESTORE_REPORT="$BACKUP_DIR/RESTORE_${STATUS}_$(date -u +%Y%m%dT%H%M%SZ).json"
{
  echo "{"
  echo "  \"status\": \"$STATUS\","
  echo "  \"path\": \"full-portable-all-services\","
  echo "  \"backup_dir\": \"$BACKUP_DIR\","
  echo "  \"signals_data_root\": \"$SIGNALS_DATA_ROOT\","
  echo "  \"finished_utc\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\","
  echo "  \"ok_count\": ${#OK[@]},"
  echo "  \"error_count\": ${#ERRORS[@]},"
  echo "  \"warning_count\": ${#WARNINGS[@]}"
  echo "}"
} > "$RESTORE_REPORT"

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
  echo "RESTORE FAILED (${#ERRORS[@]} error(s))" >&2
  for m in "${ERRORS[@]}"; do echo "  ✗ $m" >&2; done
  echo "Report: $RESTORE_REPORT" >&2
  echo "Logs:   $OUT_RESTORE_LOG" >&2
  exit 1
fi

echo ""
echo "════════════════════════════════════════════════════════════"
echo " RESTORE VERIFIED — full portable path"
echo "════════════════════════════════════════════════════════════"
echo " Identity"
echo "   source stamp:  $BACKUP_DIR"
if [ -f "$BACKUP_DIR/MANIFEST.json" ]; then
  if command -v jq >/dev/null 2>&1; then
    echo "   stamp id:      $(jq -r '.stamp // "n/a"' "$BACKUP_DIR/MANIFEST.json")"
    echo "   created_utc:   $(jq -r '.created_utc // "n/a"' "$BACKUP_DIR/MANIFEST.json")"
    echo "   backup_host:   $(jq -r '.hostname // "n/a"' "$BACKUP_DIR/MANIFEST.json")"
    echo "   path:          $(jq -r '.path // "n/a"' "$BACKUP_DIR/MANIFEST.json")"
    echo "   portable:      $(jq -r '.portable // true' "$BACKUP_DIR/MANIFEST.json")"
  else
    echo "   manifest:      $BACKUP_DIR/MANIFEST.json"
  fi
fi
echo "   data_root:     $SIGNALS_DATA_ROOT"
echo "   restore_host:  $(hostname 2>/dev/null || echo unknown)"
echo "   finished_utc:  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo " Statistics (restored)"
# Live DB stats after restore
for pair in "signals:atlas" "ranger:ranger" "signals_catalog:catalog"; do
  db="${pair%%:*}"; label="${pair##*:}"
  if psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$db" -c "SELECT 1" >/dev/null 2>&1; then
    n=$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$db" -tAc \
      "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')" \
      2>/dev/null | tr -d '[:space:]')
    ext=""
    if [ "$db" = "signals" ]; then
      age=$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$db" -tAc \
        "SELECT count(*) FROM pg_extension WHERE extname='age'" 2>/dev/null | tr -d '[:space:]')
      ext="; age_ext=${age:-0}"
    fi
    echo "   $label:  $db  user_tables=${n:-?} ${ext}"
  fi
done
if [ -d "$SIGNALS_DATA_ROOT/logical-restore/kudu" ]; then
  kt=$(find "$SIGNALS_DATA_ROOT/logical-restore/kudu" -name '*.parquet' 2>/dev/null | wc -l | tr -d ' ')
  echo "   kudu:    staged logical-restore/kudu/  parquet_files=${kt}"
  if [ -f "$SIGNALS_DATA_ROOT/logical-restore/kudu/tables.json" ] && command -v jq >/dev/null 2>&1; then
    jq -r '.tables[]? | "            \(.name): \(.rows) rows, \(.columns) cols"' \
      "$SIGNALS_DATA_ROOT/logical-restore/kudu/tables.json" 2>/dev/null || true
  fi
fi
for name in rustfs flink; do
  dvar="SIGNALS_${name^^}_DATA_DIR"
  # bash ${name^^} needs bash 4+
  case "$name" in
    rustfs) d="$SIGNALS_RUSTFS_DATA_DIR" ;;
    flink)  d="$SIGNALS_FLINK_DATA_DIR" ;;
  esac
  if [ -d "$d" ]; then
    echo "   $name:   $d  ($(du -sh "$d" 2>/dev/null | awk '{print $1}'))"
  fi
done
echo "   ok_steps: ${#OK[@]}"
echo "   report:   $RESTORE_REPORT"
echo "════════════════════════════════════════════════════════════"
echo " Restart data plane if needed: devenv up -d"
exit 0
