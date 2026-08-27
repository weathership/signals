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

# Polarisfork is class-file 61 (Java 17+). systemd PATH is OpenJDK 11.
if ! java -version 2>&1 | grep -qE 'version "1[7-9]|version "2[0-9]'; then
  for home in \
    "${JAVA_HOME:-}" \
    /nix/store/*-openjdk-21*/lib/openjdk \
    /nix/store/*-openjdk-21*; do
    [ -n "$home" ] && [ -x "$home/bin/java" ] || continue
    if "$home/bin/java" -version 2>&1 | grep -qE 'version "1[7-9]|version "2[0-9]'; then
      export JAVA_HOME="$home"
      export PATH="$JAVA_HOME/bin:$PATH"
      break
    fi
  done
fi
info "java $(java -version 2>&1 | head -1)"

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
  # Postgres :5455 is Polaris's datasource. The unit orders After=signals-ready
  # so it should be up, but wait briefly rather than launch the JVM against a
  # dead DB (which then burns the 180s readiness wait and gives up). If it never
  # comes, exit non-zero so systemd Restart re-attempts once the plane is ready.
  _pg_ok=0
  for _ in $(seq 1 60); do
    if timeout 2 bash -c "echo > /dev/tcp/127.0.0.1/5455" 2>/dev/null; then _pg_ok=1; break; fi
    sleep 2
  done
  if [[ "$_pg_ok" -ne 1 ]]; then
    info "Postgres :5455 not reachable after 120s — failing for systemd Restart"
    exit 1
  fi
  export QUARKUS_DATASOURCE_DB_KIND=postgresql
  export QUARKUS_DATASOURCE_JDBC_URL="${QUARKUS_DATASOURCE_JDBC_URL:-jdbc:postgresql://127.0.0.1:5455/polaris?currentSchema=polaris_schema}"
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
  psql -h 127.0.0.1 -p 5455 -d polaris -v ON_ERROR_STOP=1 \
    -c "CREATE SCHEMA IF NOT EXISTS polaris_schema;" >/dev/null 2>&1 || true
  if [ -x "$POLARIS_HOME/bin/admin" ]; then
    info "bootstrapping Polarisfork schema (idempotent)"
    "$POLARIS_HOME/bin/admin" bootstrap -v=3 -r=POLARIS -c=POLARIS,admin,admin -p \
      >>"$LOG_FILE" 2>&1 || info "bootstrap note (see $LOG_FILE)"
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
