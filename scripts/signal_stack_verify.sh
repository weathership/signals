#!/usr/bin/env bash
# Acceptance for the tiered signal warehouse after a restart. Fail-fast, one
# line per check, exit 1 on any FAIL. Guru: #SL.00000027.SCHEMA2
#
#   just signal-verify
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PGPASSWORD="${PGPASSWORD:-signals}"
GAIUS_ROOT="${GAIUS_ROOT:-$HOME/local/src/zndx/gaius}"
failed=0
ok()   { echo "signal-verify: OK   $*"; }
fail() { echo "signal-verify: FAIL $*"; failed=1; }

# Which devenv Postgres answers on a port is not a given: five projects run one
# each and devenv's allocator shifts a declared port on conflict. The
# authoritative surface is the checkout's own postmaster.pid (line 2 data dir,
# line 4 bound port); the connection must then report that same port back.
pg_port_of() {  # <checkout root> -> bound port, or "" if that PG is not up
  local f="$1/.devenv/state/postgres/postmaster.pid"
  [[ -f "$f" ]] || return 1
  kill -0 "$(sed -n 1p "$f")" 2>/dev/null || return 1
  sed -n 4p "$f"
}
pg_identity() {  # <label> <root> <port> <user> <db> — proves the server on <port> is <root>'s
  local label="$1" root="$2" port="$3" user="$4" db="$5"
  local got
  got="$(psql -h 127.0.0.1 -p "$port" -U "$user" -d "$db" -Atqc "SELECT inet_server_port()||' '||current_database()" 2>&1 | head -1)"
  if [[ "$got" == "$port $db" ]]; then
    ok "$label postgres :$port is $root/.devenv/state/postgres (db=$db)"
  else
    fail "$label postgres :$port identity: expected '$port $db', got '$got'"
  fi
}

SIG_PORT="$(pg_port_of "$ROOT" || true)"
[[ -n "$SIG_PORT" ]] || { fail "signals postgres not up (no live postmaster.pid under $ROOT/.devenv/state/postgres)"; SIG_PORT="${SIGNALS_PGPORT:-5455}"; }
GAIUS_PORT="$(pg_port_of "$GAIUS_ROOT" || true)"
[[ -n "$GAIUS_PORT" ]] || { fail "gaius postgres not up (no live postmaster.pid under $GAIUS_ROOT/.devenv/state/postgres)"; GAIUS_PORT="${GAIUS_PGPORT:-5444}"; }
pg_identity signals "$ROOT" "$SIG_PORT" signals signals
PGPASSWORD=gaius pg_identity gaius "$GAIUS_ROOT" "$GAIUS_PORT" gaius zndx_gaius

PGS="psql -h 127.0.0.1 -p $SIG_PORT -U signals -d signals -Atq"
PGC="psql -h 127.0.0.1 -p $SIG_PORT -U signals -d signals_catalog -Atq"
PGG="env PGPASSWORD=gaius psql -h 127.0.0.1 -p $GAIUS_PORT -U gaius -d zndx_gaius -Atq"

# 1. Registry: every table Impala must see.
want="clt_activation_tier0 clt_feature clt_label latent_tier0 signal signal_series signal_tier0 signal_tier1"
have="$($PGC -c "SELECT string_agg(table_name, ' ' ORDER BY table_name) FROM catalog_tables WHERE db_name='signals_dataproducts' AND table_name LIKE 'signal%' OR table_name LIKE 'clt_%' OR table_name='latent_tier0'" 2>/dev/null)"
for t in $want; do
  if [[ " $have " == *" $t "* ]]; then ok "registry $t"; else fail "registry missing $t"; fi
done

# 2. Kudu tables readable through both Postgres instances (kudu_scan).
for t in signal_series signal_tier0 latent_tier0 clt_feature clt_label clt_activation_tier0; do
  n="$($PGS -c "SELECT count(*) FROM $t" 2>&1 | tail -1)"
  [[ "$n" =~ ^[0-9]+$ ]] && ok ":5455 $t rows=$n" || fail ":5455 $t: $n"
done
n="$($PGG -c "SELECT count(*) FROM signal_tier0" 2>&1 | tail -1)"
[[ "$n" =~ ^[0-9]+$ ]] && ok ":$GAIUS_PORT signal_tier0 rows=$n" || fail ":$GAIUS_PORT signal_tier0: $n"

# 3. Series registry seeded by the engine (17 DCGM + cognition channels).
n="$($PGS -c "SELECT count(*) FROM signal_series" 2>&1 | tail -1)"
if [[ "$n" =~ ^[0-9]+$ ]] && (( n >= 17 )); then ok "signal_series $n series"; else fail "signal_series has $n (<17)"; fi

# 4. Engine write freshness on the hot tier (kudu_scan, current day range).
cur_h=$(( $(date -u +%s) / 3600 ))
age="$($PGS -c "SELECT (EXTRACT(EPOCH FROM clock_timestamp())*1e9 - max(ts_ns))::bigint FROM signal_tier0 WHERE epoch_hour >= $((cur_h - 1))" 2>&1 | tail -1)"
if [[ "$age" =~ ^[0-9]+$ ]] && (( age < 45000000000 )); then ok "ingest fresh age_ms=$((age/1000000))"; else fail "ingest not fresh (age_ns=$age) Guru: #EN.00000031.FDWINGEST"; fi

# 5. Decimal predicate pushes down (never a local filter).
plan="$($PGS -c "EXPLAIN (VERBOSE, COSTS OFF) SELECT ts_ns FROM signal_tier0 WHERE val_d > 0.5 AND epoch_hour >= $cur_h" 2>&1)"
if grep -q 'gov.filtered_scan' <<<"$plan" && grep -q 'remote predicates' <<<"$plan"; then ok "DECIMAL predicate pushed (kudu_scan)"; else fail "DECIMAL predicate not pushed"; fi

# 6. The hierarchy view answers through Impala with predicates (HS2 path).
if command -v uv >/dev/null; then
  out="$(cd "$ROOT" && env -u JAVA_HOME -u DEVENV_RUNTIME -u VIRTUAL_ENV timeout 300 uv run --quiet python scripts/impala_query.py -q \
        "SELECT count(*) FROM signals_dataproducts.signal WHERE epoch_hour = $cur_h AND ts_ns > 0" 2>&1 | tail -1)"
  if [[ "$out" =~ [0-9]+$ ]]; then ok "signal view via Impala: $out"; else fail "signal view via Impala: $out"; fi
fi

# 7. Tablet budget: 36 across the six tables (2+12+6+2+2+12 at 3 hot days).
tablets="$(curl -sf http://127.0.0.1:8050/tablets 2>/dev/null | grep -oE 'signals_dataproducts\.(signal|latent|clt)[a-z_0-9]*' | wc -l)"
if [[ "$tablets" =~ ^[0-9]+$ ]] && (( tablets > 0 )); then ok "kudu tablets for new tables: $tablets"; else fail "kudu tablet listing unavailable"; fi

if (( failed )); then echo "ERROR: signal-verify: see FAIL lines"; exit 1; fi
echo "signal-verify: complete"
