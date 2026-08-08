# shellcheck shell=bash
# Resolve signals-df binary (DataFusion logical backup plane).

signals_df_bin() {
  local root="${1:-${DEVENV_ROOT:-$PWD}}"
  if [ -n "${SIGNALS_DF_BIN:-}" ] && [ -x "$SIGNALS_DF_BIN" ]; then
    echo "$SIGNALS_DF_BIN"
    return 0
  fi
  local candidates=(
    "$root/target/release/signals-df"
    "$root/target/debug/signals-df"
  )
  local c
  for c in "${candidates[@]}"; do
    if [ -x "$c" ]; then
      echo "$c"
      return 0
    fi
  done
  return 1
}

# Build if missing (uses devenv languages.rust / cargo on PATH).
signals_df_ensure() {
  local root="${1:-${DEVENV_ROOT:-$PWD}}"
  if signals_df_bin "$root" >/dev/null 2>&1; then
    signals_df_bin "$root"
    return 0
  fi
  if ! command -v cargo >/dev/null 2>&1; then
    echo "ERROR: signals-df not built and cargo not on PATH (enter devenv shell)" >&2
    return 1
  fi
  echo "signals-df: building (cargo build -p signals-df)..." >&2
  (cd "$root" && cargo build -p signals-df --quiet) || {
    echo "ERROR: cargo build -p signals-df failed" >&2
    return 1
  }
  signals_df_bin "$root"
}
