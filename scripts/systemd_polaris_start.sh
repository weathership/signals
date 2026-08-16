#!/usr/bin/env bash
# Ensure Apache Polaris is up on :8181/:8182 for signals.target.
#
# Prefer the devenv process (signals.service / just up). If the catalog is
# already ready, succeed. Otherwise start the built distribution under
# .devenv/polaris so a target restart can bring the catalog back without
# cloning apache/polaris.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="/usr/local/bin:/usr/bin:/bin:${HOME}/.nix-profile/bin:${PATH:-}"

POLARIS_HOME="${POLARIS_HOME:-$ROOT/.devenv/polaris}"
LOG_DIR="${SIGNALS_POLARIS_LOG_DIR:-/tmp/signals-polaris}"
PID_FILE="$LOG_DIR/server.pid"
LOG_FILE="$LOG_DIR/server.log"
mkdir -p "$LOG_DIR"

info() { echo "signals-polaris.service: $*"; }

ready() {
  curl -sf -m 3 http://127.0.0.1:8182/q/health/ready >/dev/null 2>&1
}

if ready; then
  info "already READY (Polaris :8181/:8182)"
  exit 0
fi

if [ ! -x "$POLARIS_HOME/bin/server" ]; then
  if [ -x "$ROOT/scripts/setup_polaris_bin.sh" ] && [ -d "$POLARIS_HOME" ]; then
    "$ROOT/scripts/setup_polaris_bin.sh" "$POLARIS_HOME"
  fi
fi

if [ ! -x "$POLARIS_HOME/bin/server" ]; then
  info "Polaris not installed at $POLARIS_HOME — waiting for devenv process"
else
  info "starting Polaris from $POLARIS_HOME"
  export QUARKUS_DATASOURCE_DB_KIND=postgresql
  export QUARKUS_DATASOURCE_JDBC_URL="${QUARKUS_DATASOURCE_JDBC_URL:-jdbc:postgresql://127.0.0.1:5455/polaris}"
  export QUARKUS_DATASOURCE_USERNAME="${QUARKUS_DATASOURCE_USERNAME:-signals}"
  export QUARKUS_DATASOURCE_PASSWORD="${QUARKUS_DATASOURCE_PASSWORD:-signals}"
  export POLARIS_PERSISTENCE_TYPE=relational-jdbc
  export AWS_ENDPOINT_URL="${AWS_ENDPOINT_URL:-http://127.0.0.1:9010}"
  export AWS_REGION="${AWS_REGION:-us-east-1}"
  export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-${RUSTFS_ACCESS_KEY:-rustfsadmin}}"
  export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-${RUSTFS_SECRET_KEY:-rustfsadmin}}"
  export JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS:-} -Daws.endpointUrl=http://127.0.0.1:9010 -Daws.region=us-east-1 -Daws.s3.pathStyleAccessEnabled=true -Dquarkus.http.host=127.0.0.1"
  if [ -f "$ROOT/config/polaris/application.properties" ]; then
    export JAVA_TOOL_OPTIONS="$JAVA_TOOL_OPTIONS -Dquarkus.config.locations=$ROOT/config/polaris/application.properties"
  fi
  nohup "$POLARIS_HOME/bin/server" >>"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"
fi

for i in $(seq 1 90); do
  if ready; then
    info "READY after ${i}s"
    exit 0
  fi
  sleep 2
done

info "Polaris not ready on :8182 after 180s"
exit 1
