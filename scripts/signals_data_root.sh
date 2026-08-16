# shellcheck shell=bash
# Shared Signals durable storage root (sourced by devenv processes + backup).
#
# Layout (user-chosen root; lab default /raid/signals):
#   $SIGNALS_DATA_ROOT/
#     kudu/       — Kudu master + tserver data/wal/logs
#     rustfs/     — object store (sibling of kudu; S3/Iceberg warm path)
#     flink/      — Flink checkpoints / savepoints (when enabled)
#     backups/    — just backup output (portable Atlas/Ranger/PG dumps)
#
# Override: SIGNALS_DATA_ROOT in .env or the environment.
# Fallback: $PWD/.devenv/signals-data when the preferred root is missing/unwritable.

signals_resolve_data_root() {
  local preferred fallback
  preferred="${SIGNALS_DATA_ROOT:-/raid/signals}"
  fallback="${SIGNALS_DATA_FALLBACK:-}"
  if [ -z "$fallback" ]; then
    if [ -n "${DEVENV_ROOT:-}" ]; then
      fallback="$DEVENV_ROOT/.devenv/signals-data"
    elif [ -n "${PWD:-}" ]; then
      fallback="$PWD/.devenv/signals-data"
    else
      fallback="${HOME}/.local/signals-data"
    fi
  fi

  if [ -d "$preferred" ] && [ -w "$preferred" ]; then
    SIGNALS_DATA_ROOT="$preferred"
  elif mkdir -p "$preferred" 2>/dev/null && [ -w "$preferred" ]; then
    SIGNALS_DATA_ROOT="$preferred"
  else
    mkdir -p "$fallback"
    SIGNALS_DATA_ROOT="$fallback"
    if [ "${SIGNALS_DATA_ROOT_WARNED:-0}" != "1" ]; then
      echo "signals_data_root: using fallback $SIGNALS_DATA_ROOT (preferred $preferred not usable)" >&2
      export SIGNALS_DATA_ROOT_WARNED=1
    fi
  fi

  export SIGNALS_DATA_ROOT
  export SIGNALS_KUDU_HOME="${SIGNALS_KUDU_HOME:-$SIGNALS_DATA_ROOT/kudu}"
  export SIGNALS_RUSTFS_DATA_DIR="${SIGNALS_RUSTFS_DATA_DIR:-$SIGNALS_DATA_ROOT/rustfs}"
  export RUSTFS_DATA_DIR="${RUSTFS_DATA_DIR:-$SIGNALS_RUSTFS_DATA_DIR}"
  export SIGNALS_FLINK_DATA_DIR="${SIGNALS_FLINK_DATA_DIR:-$SIGNALS_DATA_ROOT/flink}"
  export SIGNALS_BACKUP_DIR="${SIGNALS_BACKUP_DIR:-$SIGNALS_DATA_ROOT/backups}"
}

signals_ensure_data_layout() {
  signals_resolve_data_root
  mkdir -p \
    "$SIGNALS_KUDU_HOME/master/data" \
    "$SIGNALS_KUDU_HOME/master/wal" \
    "$SIGNALS_KUDU_HOME/master/logs" \
    "$SIGNALS_KUDU_HOME/tserver/data" \
    "$SIGNALS_KUDU_HOME/tserver/wal" \
    "$SIGNALS_KUDU_HOME/tserver/logs" \
    "$SIGNALS_RUSTFS_DATA_DIR" \
    "$SIGNALS_FLINK_DATA_DIR" \
    "$SIGNALS_BACKUP_DIR" \
    "$SIGNALS_DATA_ROOT/impala/s3a-buffer" \
    "$SIGNALS_DATA_ROOT/impala/hadoop-tmp"
}
