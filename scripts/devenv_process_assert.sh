#!/usr/bin/env bash
# Assert expected host processes are up without calling `devenv` (nested devenv
# from a before-task deadlocks on tasks.db under native manager).
#
# Uses: process log files under $XDG_RUNTIME_DIR/devenv-*/processes/logs/
#       + TCP/HTTP port probes (source of truth for "ready").
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

info() { echo "process-assert: $*"; }
die() { echo "ERROR: process-assert: $*" >&2; exit 1; }

# name:host:port:proto (http|tcp)
# signals-ui intentionally omitted when used from stack-ready (before that process).
PROBES=(
  "postgres:127.0.0.1:5455:tcp"
  "kdc:127.0.0.1:8848:udp"
  "rustfs:127.0.0.1:9010:tcp"
  "atlas:127.0.0.1:21010:http"
  "marquez-web:127.0.0.1:21011:http"
  "ranger-admin:127.0.0.1:6080:tcp"
  "kudu-master:127.0.0.1:8051:http"
  "kudu-tserver:127.0.0.1:8050:http"
)
if [[ "$(uname -s)" == "Linux" ]]; then
  PROBES+=(
    "impala-statestore:127.0.0.1:25010:http"
    "impala-catalogd:127.0.0.1:25020:http"
    "impala-impalad:127.0.0.1:25000:http"
  )
fi
if [[ "${SIGNALS_PROCESS_ASSERT_INCLUDE_UI:-0}" == "1" ]]; then
  PROBES+=("signals-ui:127.0.0.1:9889:http")
fi

tcp_ok() { timeout 2 bash -c "echo >/dev/tcp/${1}/${2}" 2>/dev/null; }
udp_ok() {
  # KDC: ss listen check (UDP connect is unreliable)
  ss -uln 2>/dev/null | grep -qE ":${2}\\s"
}
http_ok() { curl -sf -m 3 "http://${1}:${2}/" >/dev/null 2>&1 \
  || curl -sf -m 3 "http://${1}:${2}/api/atlas/admin/status" >/dev/null 2>&1 \
  || curl -sf -m 3 "http://${1}:${2}/readyz" >/dev/null 2>&1 \
  || curl -sf -m 3 "http://${1}:${2}/healthcheck" >/dev/null 2>&1; }

# Optional: log dir presence (process was at least scheduled)
find_log_dir() {
  local d
  for d in \
    "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"/devenv-*/processes/logs \
    /run/user/$(id -u)/devenv-*/processes/logs; do
    # shellcheck disable=SC2086
    for x in $d; do
      [[ -d "$x" ]] && { echo "$x"; return 0; }
    done
  done
  return 1
}

LOG_DIR="$(find_log_dir || true)"
if [[ -n "$LOG_DIR" ]]; then
  info "log dir: $LOG_DIR"
else
  info "WARN no process log dir (manager may not be up yet)"
fi

WAIT="${SIGNALS_PROCESS_ASSERT_WAIT:-120}"
missing=()
for entry in "${PROBES[@]}"; do
  IFS=':' read -r name host port proto <<<"$entry"
  ok=0
  for _ in $(seq 1 "$WAIT"); do
    case "$proto" in
      tcp) tcp_ok "$host" "$port" && ok=1 ;;
      udp) udp_ok "$host" "$port" && ok=1 ;;
      http) http_ok "$host" "$port" && ok=1 ;;
    esac
    [[ "$ok" -eq 1 ]] && break
    # short wait only if we're still within budget
    sleep 1
  done
  if [[ "$ok" -eq 1 ]]; then
    info "OK  $name :$port"
  else
    info "MISSING $name :$port ($proto)"
    missing+=("$name")
  fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
  cat >&2 <<EOF
ERROR: process-assert: not ready after ${WAIT}s:

  ${missing[*]}

Full graph:
  devenv processes down
  just stack-reset   # or: devenv up -d
EOF
  exit 1
fi

info "OK — all expected data-plane/host processes up (${#PROBES[@]})"
exit 0
