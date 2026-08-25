#!/usr/bin/env bash
# Lattice-safe foundation stop for signals.service (systemd).
# Reap wrapper Impala / sidecar ingest that devenv does not own so the next
# `just up` can bind HS2 and the engine is the only warehouse writer.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="/usr/local/bin:/usr/bin:/bin:${HOME}/.nix-profile/bin:${PATH:-}"

echo "systemd-foundation: just down"
just down || true

# `just down` only sees the compose under the login shell's runtime dir. A
# graph started at boot before /run/user/<uid> existed lives under /tmp, and
# a graph started from another shell may sit under a different DEVENV_RUNTIME.
# Reap every devenv process-compose daemon whose cwd is THIS checkout, wherever
# its runtime is, so a foundation stop is a foundation stop.
compose_pids() {
  local pid args cwd
  while read -r pid args; do
    [[ "$args" == *devenv-wrapped*daemon-processes* ]] || continue
    cwd=$(readlink "/proc/${pid}/cwd" 2>/dev/null || true)
    [[ "$cwd" == "$ROOT" ]] || continue
    printf '%s\n' "$pid"
  done < <(ps -eo pid=,args=)
}
for pid in $(compose_pids); do
  echo "systemd-foundation: TERM devenv compose pid=$pid (cwd=$ROOT)"
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
done
for _ in $(seq 1 60); do
  [[ -z "$(compose_pids || true)" ]] && break
  sleep 1
done
for pid in $(compose_pids); do
  echo "systemd-foundation: KILL devenv compose pid=$pid after grace"
  kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
done

reap_listen_port() {
  local port="$1"
  local pid
  pid="$(ss -lntp 2>/dev/null | awk -v p=":${port}" '
    $4 ~ p"$" {
      if (match($0, /pid=[0-9]+/)) {
        s=substr($0, RSTART+4, RLENGTH-4)
        print s
      }
    }' | sort -u | head -1)"
  if [[ -n "${pid:-}" ]]; then
    echo "systemd-foundation: reap pid $pid still on :$port"
    kill "$pid" 2>/dev/null || true
  fi
}

# Impala ports — leftover /tmp start-impala-hs2.sh daemons bind these.
for port in 21050 25000 25020 26000 24000 25010; do
  reap_listen_port "$port"
done

# Ad-hoc C++ sidecar writer (product writer is Gaius engine FDW INSERT).
while read -r pid; do
  [[ -z "$pid" ]] && continue
  echo "systemd-foundation: reap sidecar ingest pid $pid"
  kill "$pid" 2>/dev/null || true
done < <(pgrep -f 'scripts/gpu_metrics_kudu_ingest.py' || true)

# Host :9400 nvidia-smi shim — engine HardwareDriver samples nvidia-smi itself.
reap_listen_port 9400

# A stop that leaves the foundation listening is not a stop. Kudu master/
# tserver, Postgres, Polaris, HS2.
still=""
for _ in $(seq 1 30); do
  still=""
  for port in 7051 7050 5455 8181 21050; do
    ss -ltnH 2>/dev/null | grep -qE ":${port}[[:space:]]" && still="$still $port"
  done
  [[ -z "$still" ]] && break
  sleep 1
done
if [[ -n "$still" ]]; then
  echo "ERROR: systemd-foundation: still listening after stop:$still (Guru: #SL.00000030.NOTSTOPPED)" >&2
  ss -ltnpH 2>/dev/null | grep -E ":(7051|7050|5455|8181|21050)[[:space:]]" >&2 || true
  exit 1
fi
echo "systemd-foundation: foundation ports free; compose reaped"
