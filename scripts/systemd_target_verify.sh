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
for u in "${UNITS[@]}"; do
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
fi

if [[ "$failed" -ne 0 ]]; then
  die "group refresh incomplete — see FAIL lines. Do not treat signals.target as healthy."
fi
info "group refresh complete (${#UNITS[@]} members)"
