#!/usr/bin/env bash
# Restart the (orphaned) Atlas JVM onto the freshly built webapp.
#
# Context (2026-08-31): the signals devenv stack was started from an
# interactive session whose native process manager has since died, so
# `devenv processes restart atlas` reports "No process manager is running"
# and no systemd unit owns the Atlas JVM. This script stops the orphan and
# relaunches Atlas with the SAME JVM and the SAME exec as
# devenv.nix processes.atlas, logging to the same devenv log files.
# It is a stopgap until the stack is brought back under a live manager
# (next full `devenv up -d` / stack recycle supersedes this).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ATLAS_DIR="$ROOT/components/atlas"
ATLAS_WEBAPP="$ATLAS_DIR/webapp/target/atlas-webapp-3.0.0-SNAPSHOT"
ATLAS_CONF_SRC="$ROOT/config/atlas"
ATLAS_HOME="$ROOT/.devenv/atlas"
# NEVER trust an inherited PGPORT — a shell launched from another project's
# devenv (e.g. gaius, PGPORT=5444) silently points Atlas at the wrong
# Postgres. Signals PG is :5455; override only via SIGNALS_PGPORT.
PGPORT="${SIGNALS_PGPORT:-5455}"
LOGDIR="${ATLAS_PROC_LOGDIR:-/run/user/$(id -u)/devenv-85cf547/processes/logs}"

if [ ! -d "$ATLAS_WEBAPP/WEB-INF" ]; then
  echo "Atlas webapp not built. Run: devenv tasks run atlas:build" >&2
  exit 1
fi

# The maven-war packaging has been observed to ship a STALE
# WEB-INF/classes copy while target/classes holds the fresh compile
# (2026-08-31). The runtime classpath puts WEB-INF/classes first, so
# overlay the freshly compiled openlineage package before launching.
FRESH="$ATLAS_DIR/webapp/target/classes/org/apache/atlas/openlineage"
DEPLOYED="$ATLAS_WEBAPP/WEB-INF/classes/org/apache/atlas/openlineage"
if [ -d "$FRESH" ] && [ -d "$DEPLOYED" ]; then
  cp -f "$FRESH"/*.class "$DEPLOYED"/
fi

# Find the running Atlas for THIS checkout (if any) and reuse its JVM.
PID="$(pgrep -f "atlas.home=$ROOT/.devenv/atlas" | head -1 || true)"
JAVA=""
if [ -n "$PID" ]; then
  JAVA="$(readlink "/proc/$PID/exe" || true)"
  echo "stopping atlas pid $PID"
  kill "$PID"
  for _ in $(seq 1 30); do [ ! -d "/proc/$PID" ] && break; sleep 2; done
  if [ -d "/proc/$PID" ]; then
    echo "SIGTERM ignored; SIGKILL"
    kill -9 "$PID"
    sleep 3
  fi
fi
if [ -z "$JAVA" ] || [ ! -x "$JAVA" ]; then
  JAVA="${JAVA_BIN:-$(command -v java)}"
fi
echo "using JVM: $JAVA"

mkdir -p "$ATLAS_HOME/data" "$ATLAS_HOME/logs" "$ATLAS_HOME/conf" "$LOGDIR"
ln -sfn "$ATLAS_DIR/addons/models" "$ATLAS_HOME/models"
sed -e "s|localhost:[0-9]*/signals|localhost:$PGPORT/signals|" \
    -e "s|atlas.age.jdbc.user=.*|atlas.age.jdbc.user=signals|" \
    -e "s|atlas.age.jdbc.password=.*|atlas.age.jdbc.password=signals|" \
  "$ATLAS_CONF_SRC/atlas-application.properties" > "$ATLAS_HOME/conf/atlas-application.properties"
cp -f "$ATLAS_CONF_SRC/users-credentials.properties" "$ATLAS_HOME/conf/" 2>/dev/null || true
cp -f "$ATLAS_CONF_SRC/atlas-simple-authz-policy.json" "$ATLAS_HOME/conf/" 2>/dev/null || true

for _ in $(seq 1 90); do
  pg_isready -h localhost -p "$PGPORT" -q && break
  sleep 1
done

echo "Starting Atlas on http://localhost:21010 (AGE -> signals DB, pg :$PGPORT)..."
nohup "$JAVA" \
  -Datlas.home="$ATLAS_HOME" -Datlas.conf="$ATLAS_HOME/conf" \
  -Datlas.log.dir="$ATLAS_HOME/logs" -Datlas.log.file=application \
  -Datlas.data="$ATLAS_HOME/data" \
  -Dlogback.configurationFile="$ATLAS_DIR/distro/src/conf/atlas-logback.xml" \
  -Datlas.graphdb.backend=org.apache.atlas.repository.graphdb.age.AtlasAgeGraphDatabase \
  -Djava.net.preferIPv4Stack=true \
  --add-opens java.base/java.lang=ALL-UNNAMED \
  --add-opens java.base/java.lang.reflect=ALL-UNNAMED \
  --add-opens java.base/java.io=ALL-UNNAMED \
  --add-opens java.base/java.net=ALL-UNNAMED \
  --add-opens java.base/java.util=ALL-UNNAMED \
  --add-opens java.base/java.util.concurrent=ALL-UNNAMED \
  --add-opens java.base/sun.nio.ch=ALL-UNNAMED \
  --add-opens java.base/sun.security.action=ALL-UNNAMED \
  --add-opens java.security.jgss/sun.security.krb5=ALL-UNNAMED \
  -server -Xmx1024m \
  -cp "$ATLAS_HOME/conf:$ATLAS_WEBAPP/WEB-INF/classes:$ATLAS_WEBAPP/WEB-INF/lib/*" \
  org.apache.atlas.Atlas -app "$ATLAS_WEBAPP" -port 21010 \
  > "$LOGDIR/atlas.stdout.log" 2> "$LOGDIR/atlas.stderr.log" &
echo "atlas relaunched pid $!"

for i in $(seq 1 50); do
  if curl -sf --max-time 4 http://127.0.0.1:21010/api/atlas/admin/status >/dev/null 2>&1; then
    echo "atlas READY after ~$((i * 6))s"
    exit 0
  fi
  sleep 6
done
echo "atlas NOT ready after ~5min — check $LOGDIR/atlas.stderr.log" >&2
exit 1
