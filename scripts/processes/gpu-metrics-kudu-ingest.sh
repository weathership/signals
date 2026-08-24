#!/usr/bin/env bash
# Ops-only C++ sidecar. Product writer is Gaius engine warehouse_ingest
# (Postgres INSERT → impala_fdw kudu_scan UPSERT). Guru: #EN.00000031.FDWINGEST
# Guru: #SL.00000024.GPUINGEST
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

# shellcheck source=/dev/null
. "$ROOT/scripts/signals_data_root.sh"
signals_ensure_data_layout

KDC_DIR="$ROOT/.devenv/kdc"
if [ -f "$KDC_DIR/krb5.conf" ]; then
  export KRB5_CONFIG="$KDC_DIR/krb5.conf"
fi
export KRB5CCNAME="${KRB5CCNAME:-$KDC_DIR/krb5cc}"
export KUDU_MASTERS="${KUDU_MASTERS:-${SIGNALS_KRB_HOST:-tinybox.dev.vista.zndx.org}:7051}"
export SIGNALS_ROOT="$ROOT"
export SIGNALS_GPU_METRICS_DIR="${SIGNALS_GPU_METRICS_DIR:-$SIGNALS_DATA_ROOT/gpu-metrics}"
export GPU_METRICS_JSONL="${GPU_METRICS_JSONL:-$SIGNALS_GPU_METRICS_DIR/hour.jsonl}"
export GPU_METRICS_STATUS="${GPU_METRICS_STATUS:-$SIGNALS_GPU_METRICS_DIR/ingest.status}"
export GPU_METRICS_INTERVAL_S="${GPU_METRICS_INTERVAL_S:-1}"

# Static C++ helpers are ~150 MiB each — keep them on raid, not nodefs.
BINDIR="${SIGNALS_GPU_METRICS_BIN:-$SIGNALS_DATA_ROOT/bin}"
mkdir -p "$BINDIR"
for b in gpu_kudu_create gpu_kudu_ingest; do
  if [ ! -x "$BINDIR/$b" ]; then
    if [ -x "$ROOT/.devenv/bin/$b" ]; then
      cp -a "$ROOT/.devenv/bin/$b" "$BINDIR/$b"
    elif [ -x "/tmp/$b" ]; then
      cp -a "/tmp/$b" "$BINDIR/$b"
    fi
  fi
done
export GPU_KUDU_CREATE="${GPU_KUDU_CREATE:-$BINDIR/gpu_kudu_create}"
export GPU_KUDU_INGEST="${GPU_KUDU_INGEST:-$BINDIR/gpu_kudu_ingest}"
if [ ! -x "$GPU_KUDU_CREATE" ] || [ ! -x "$GPU_KUDU_INGEST" ]; then
  echo "ERROR: #SL.00000024.GPUINGEST missing C++ helpers"
  echo "  Expected: $GPU_KUDU_CREATE and $GPU_KUDU_INGEST"
  echo "  Build scripts/gpu_kudu_create.cc and gpu_kudu_ingest.cc into .devenv/bin/"
  exit 1
fi

if [ -f "$KDC_DIR/signals.keytab" ] && command -v kinit >/dev/null 2>&1; then
  kinit -kt "$KDC_DIR/signals.keytab" \
    "signals@${SIGNALS_KRB_REALM:-DEV.VISTA.ZNDX.ORG}" >/dev/null || true
fi

# Wait for tserver web (process-compose also depends_on kudu-tserver).
for _ in $(seq 1 60); do
  if curl -sf -o /dev/null http://127.0.0.1:8050/; then
    break
  fi
  sleep 1
done

echo "ERROR: #EN.00000031.FDWINGEST sidecar Kudu writer is retired."
echo "  Product path: Gaius engine INSERT INTO gpu_metrics_tier0 via impala_fdw."
exit 1
