#!/usr/bin/env bash
# After signals.target start/restart: every enabled member must be active,
# and every enabled lattice engine must answer Engine/Status.
# Fail-fast — a "successful" refresh with a dead peer is not a refresh.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WANTS="${SIGNALS_TARGET_WANTS:-/etc/systemd/system/signals.target.wants}"
CONTRACT="${SIGNALS_PEER_CONTRACT:-$ROOT/config/platform/peer-contract.json}"

info() { echo "signals-refresh: $*"; }
die() { echo "ERROR: signals-refresh: $*" >&2; exit 1; }

[[ -d "$WANTS" ]] || die "missing $WANTS (enable signals.target members)"
[[ -f "$CONTRACT" ]] || die "missing $CONTRACT"

mapfile -t UNITS < <(find "$WANTS" -maxdepth 1 -type l -printf '%f\n' | sort)
[[ ${#UNITS[@]} -gt 0 ]] || die "no enabled members under $WANTS"

failed=0
SELF="${SIGNALS_REFRESH_UNIT:-signals-refresh.service}"
for u in "${UNITS[@]}"; do
  # This script IS signals-refresh.service's ExecStart: while it runs the unit
  # is necessarily `activating`, so checking it here failed every refresh.
  if [[ "$u" == "$SELF" ]]; then
    info "SELF $u (verifier; not a member to check)"
    continue
  fi
  st=$(systemctl is-active "$u" 2>/dev/null || true)
  if [[ "$st" != "active" ]]; then
    info "FAIL $u is-active=$st"
    failed=1
  else
    info "OK   $u"
  fi
done

# Lattice Status for enabled units that map to a contract peer.
if command -v python3 >/dev/null; then
  while IFS=$'\t' read -r unit port; do
    [[ -z "$unit" || -z "$port" ]] && continue
    if [[ ! -e "$WANTS/$unit" ]]; then
      continue
    fi
    if grpcurl -plaintext "127.0.0.1:${port}" zndx.engine.v1.Engine/Status >/dev/null 2>&1; then
      info "OK   $unit Engine/Status :${port}"
    else
      info "FAIL $unit Engine/Status :${port} unreachable"
      failed=1
    fi
  done < <(python3 - "$CONTRACT" <<'PY'
import json, sys
c = json.load(open(sys.argv[1]))
for p in c.get("peers") or []:
    unit = p.get("unit") or ""
    port = p.get("grpc_port")
    if unit and port:
        print(f"{unit}\t{port}")
PY
)
fi

# Gaius product UI is part of that peer's full stack.
if [[ -e "$WANTS/gaius.service" ]]; then
  if ss -ltnH 2>/dev/null | grep -qE ':9890[[:space:]]'; then
    info "OK   gaius-ui :9890"
  else
    info "FAIL gaius-ui :9890 not listening (full-stack doctrine)"
    failed=1
  fi
  # Engine warehouse ingest: FDW INSERT freshness (max ts within 45s).
  # Read the hot tier directly (kudu_scan, ~10 ms). The UNION view would drag
  # every settled hour through Impala for one max(), which is a scan of the
  # whole history on every refresh.
  fresh=0
  cur_h=$(( $(date -u +%s) / 3600 ))
  # The signals PG port comes from the checkout's own postmaster.pid, not a
  # literal: devenv shifts ports on conflict and other projects' PGs are near.
  pidf="$ROOT/.devenv/state/postgres/postmaster.pid"
  sig_port="$( [[ -f "$pidf" ]] && sed -n 4p "$pidf" || echo "${SIGNALS_PG_PORT:-5455}")"
  for _ in $(seq 1 15); do
    age_ns="$(PGPASSWORD="${PGPASSWORD:-signals}" psql -h 127.0.0.1 -p "$sig_port" \
      -U signals -d signals -Atqc \
      "SELECT (EXTRACT(EPOCH FROM clock_timestamp())*1e9 - max(ts_ns))::bigint FROM signal_tier0 WHERE epoch_hour >= $((cur_h - 1))" \
      2>/dev/null || echo "")"
    if [[ -n "$age_ns" && "$age_ns" =~ ^[0-9]+$ ]] && (( age_ns < 45000000000 )); then
      info "OK   warehouse ingest age_ns=$age_ns"
      fresh=1
      break
    fi
    sleep 2
  done
  if [[ "$fresh" -ne 1 ]]; then
    info "FAIL warehouse ingest not fresh (impala_fdw INSERT). Guru: #EN.00000031.FDWINGEST"
    failed=1
  fi
fi

if [[ "$failed" -ne 0 ]]; then
  die "group refresh incomplete — see FAIL lines. Do not treat signals.target as healthy."
fi
info "group refresh complete (${#UNITS[@]} members)"
