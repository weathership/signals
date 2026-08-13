#!/usr/bin/env bash
# lattice-ci — elevated CI gate: probe zndx.engine.v1.Engine/Status on the gRPC lattice.
#
# Accept path uses gRPC *server reflection* (signals-protocol requirement):
#   grpcurl -plaintext host:port zndx.engine.v1.Engine/Status
# Engines MUST enable reflection on the lattice port. Local -proto is not accept.
#
# Reads config/platform/peer-contract.json. Default: peers that are *listening*
# or have an active systemd unit are required; others are SKIP (not FAIL).
#
# Usage:
#   just lattice-ci
#   scripts/lattice_ci.sh
#   scripts/lattice_ci.sh --json
#   scripts/lattice_ci.sh --require gaius,metabase
#   scripts/lattice_ci.sh --all
#   SIGNALS_LATTICE_REQUIRE=gaius,metabase scripts/lattice_ci.sh
#
# Not foundation readiness — use just signals-ready for critical plane.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CONTRACT="${SIGNALS_PEER_CONTRACT:-$ROOT/config/platform/peer-contract.json}"
FORMAT=text
REQUIRE_CSV="${SIGNALS_LATTICE_REQUIRE:-}"
REQUIRE_ALL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json) FORMAT=json ;;
    --all) REQUIRE_ALL=1 ;;
    --require)
      shift
      REQUIRE_CSV="${1:-}"
      [[ -n "$REQUIRE_CSV" ]] || { echo "ERROR: --require needs a CSV list" >&2; exit 2; }
      ;;
    --require=*) REQUIRE_CSV="${1#--require=}" ;;
    -h|--help)
      sed -n '2,18p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "ERROR: unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

[[ -f "$CONTRACT" ]] || { echo "ERROR: lattice-ci: missing $CONTRACT" >&2; exit 2; }

if ! command -v grpcurl >/dev/null 2>&1; then
  echo "ERROR: lattice-ci: grpcurl not on PATH" >&2
  exit 2
fi

PROTO_DIR="$ROOT/components/signals-protocol/proto"

tcp_listen() {
  local port="$1"
  ss -ltn 2>/dev/null | grep -qE ":${port}\\s"
}

unit_active() {
  systemctl is-active --quiet "$1" 2>/dev/null
}

mapfile -t PEER_LINES < <(python3 - <<PY
import json
from pathlib import Path
c = json.loads(Path(r"""$CONTRACT""").read_text())
svc = c.get("engine_grpc_lattice", {}).get("service", "zndx.engine.v1.Engine")
print(f"__SERVICE__|{svc}")
for p in c.get("peers", []):
    pid = p["id"]
    port = p.get("grpc_port") or c.get("engine_grpc_lattice", {}).get(pid, "")
    unit = p.get("unit", f"{pid}.service")
    cap = p.get("capability") or p.get("capability_hint") or ""
    proj = p.get("project_status") or pid
    print(f"{pid}|{port}|{unit}|{cap}|{proj}")
PY
)

SERVICE="zndx.engine.v1.Engine"
for line in "${PEER_LINES[@]}"; do
  if [[ "$line" == __SERVICE__\|* ]]; then
    SERVICE="${line#__SERVICE__|}"
  fi
done
METHOD="${SERVICE}/Status"

declare -A REQUIRED=()
if [[ "$REQUIRE_ALL" == "1" ]]; then
  for line in "${PEER_LINES[@]}"; do
    [[ "$line" == __SERVICE__\|* ]] && continue
    REQUIRED["${line%%|*}"]=1
  done
fi
if [[ -n "$REQUIRE_CSV" ]]; then
  IFS=',' read -ra _req <<<"$REQUIRE_CSV"
  for r in "${_req[@]}"; do
    r="${r// /}"
    [[ -n "$r" ]] && REQUIRED["$r"]=1
  done
fi

RESULTS=()
FAILS=0
PASSES=0
SKIPS=0

# Federation accept uses gRPC server reflection (signals-protocol requirement).
# Bare grpcurl against the live port — no local -proto path for accept.
probe_status() {
  local port="$1"
  local out err
  err=$(mktemp)
  if out=$(grpcurl -plaintext -max-time 3 "127.0.0.1:${port}" "$METHOD" 2>"$err"); then
    rm -f "$err"
    printf '%s' "$out"
    return 0
  fi
  # Distinguish missing reflection from missing Status implementation
  if grep -qi 'reflection' "$err" 2>/dev/null; then
    rm -f "$err"
    echo "__NO_REFLECTION__"
    return 2
  fi
  rm -f "$err"
  return 1
}

SCHEMA="$(python3 -c "import json; print(json.load(open(r'''$CONTRACT'''))['schema_version'])")"
echo "lattice-ci: gRPC Status probe (contract schema_version=${SCHEMA})"
printf '%-12s %-6s %-6s %s\n' "PEER" "PORT" "STATUS" "DETAIL"
printf '%-12s %-6s %-6s %s\n' "----" "----" "------" "------"

for line in "${PEER_LINES[@]}"; do
  [[ "$line" == __SERVICE__\|* ]] && continue
  IFS='|' read -r pid port unit cap proj <<<"$line"
  [[ -n "$port" ]] || continue

  must=0
  [[ -n "${REQUIRED[$pid]:-}" ]] && must=1

  listening=0
  tcp_listen "$port" && listening=1
  active=0
  unit_active "$unit" && active=1

  if [[ "$must" -eq 0 && ( "$listening" -eq 1 || "$active" -eq 1 ) ]]; then
    must=1
  fi

  if [[ "$listening" -eq 0 && "$must" -eq 0 ]]; then
    RESULTS+=("${pid}|${port}|SKIP|not listening; unit inactive")
    SKIPS=$((SKIPS + 1))
    printf '%-12s %-6s %-6s %s\n' "$pid" "$port" "SKIP" "not listening"
    continue
  fi

  if [[ "$listening" -eq 0 && "$must" -eq 1 ]]; then
    RESULTS+=("${pid}|${port}|FAIL|required but not listening (unit=$unit)")
    FAILS=$((FAILS + 1))
    printf '%-12s %-6s %-6s %s\n' "$pid" "$port" "FAIL" "required, not listening"
    continue
  fi

  body=""
  rc=0
  body=$(probe_status "$port") || rc=$?
  if [[ "$rc" -eq 0 && -n "$body" && "$body" != "__NO_REFLECTION__" ]]; then
    detail="Status OK (reflection)"
    if [[ -n "$proj" ]] && ! echo "$body" | grep -qi "$proj"; then
      detail="Status OK (project '$proj' not in body — soft)"
    fi
    if [[ -n "$cap" ]] && ! echo "$body" | grep -qi "$cap"; then
      detail="${detail}; capability '$cap' not in body — soft"
    fi
    RESULTS+=("${pid}|${port}|PASS|${detail}")
    PASSES=$((PASSES + 1))
    printf '%-12s %-6s %-6s %s\n' "$pid" "$port" "PASS" "$detail"
  elif [[ "$rc" -eq 2 || "$body" == "__NO_REFLECTION__" ]]; then
    RESULTS+=("${pid}|${port}|FAIL|gRPC reflection required (enable grpcio-reflection / ServerReflection)")
    FAILS=$((FAILS + 1))
    printf '%-12s %-6s %-6s %s\n' "$pid" "$port" "FAIL" "reflection required"
  else
    RESULTS+=("${pid}|${port}|FAIL|listening but Status RPC failed (method missing or error)")
    FAILS=$((FAILS + 1))
    printf '%-12s %-6s %-6s %s\n' "$pid" "$port" "FAIL" "Status RPC failed"
  fi
done

echo
echo "summary: pass=${PASSES} fail=${FAILS} skip=${SKIPS}"

if [[ "$FORMAT" == "json" ]]; then
  export SIGNALS_LATTICE_RESULTS SIGNALS_LATTICE_PASS SIGNALS_LATTICE_FAIL SIGNALS_LATTICE_SKIP
  SIGNALS_LATTICE_RESULTS="$(printf '%s\n' "${RESULTS[@]}")"
  SIGNALS_LATTICE_PASS="$PASSES"
  SIGNALS_LATTICE_FAIL="$FAILS"
  SIGNALS_LATTICE_SKIP="$SKIPS"
  python3 - <<'PY'
import json, os
checks = []
for line in os.environ.get("SIGNALS_LATTICE_RESULTS", "").splitlines():
    if not line.strip():
        continue
    parts = line.split("|", 3)
    if len(parts) < 4:
        continue
    pid, port, status, detail = parts
    checks.append({"peer": pid, "port": int(port), "status": status.lower(), "detail": detail})
print(json.dumps({
    "ok": int(os.environ.get("SIGNALS_LATTICE_FAIL", "1")) == 0,
    "pass": int(os.environ.get("SIGNALS_LATTICE_PASS", "0")),
    "fail": int(os.environ.get("SIGNALS_LATTICE_FAIL", "0")),
    "skip": int(os.environ.get("SIGNALS_LATTICE_SKIP", "0")),
    "checks": checks,
}, indent=2))
PY
fi

if [[ "$FAILS" -gt 0 ]]; then
  echo "lattice-ci: FAIL (${FAILS})" >&2
  exit 1
fi
echo "lattice-ci: OK"
exit 0
