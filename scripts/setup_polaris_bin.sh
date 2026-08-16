#!/usr/bin/env bash
# Wrapper scripts for a Polaris quarkus-app / polaris-bin distribution.
#
# Usage: scripts/setup_polaris_bin.sh [POLARIS_HOME]
# Default POLARIS_HOME: $PWD/.devenv/polaris
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POLARIS_HOME="${1:-${POLARIS_HOME:-$ROOT/.devenv/polaris}}"

if [ ! -d "$POLARIS_HOME" ]; then
  echo "ERROR: Polaris home not found: $POLARIS_HOME" >&2
  echo "  devenv tasks run polaris:install" >&2
  exit 1
fi

BIN_DIR="$POLARIS_HOME/bin"
CONF_DIR="$POLARIS_HOME/conf"
mkdir -p "$BIN_DIR" "$CONF_DIR"

# Support both cybersec polaris-bin layout (server/quarkus-run.jar) and
# signals polaris:install layout (polaris-quarkus-server.jar at root).
cat > "$BIN_DIR/admin" << 'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POLARIS_HOME="$(dirname "$SCRIPT_DIR")"
if [ -f "$POLARIS_HOME/admin/quarkus-run.jar" ]; then
  exec java -jar "$POLARIS_HOME/admin/quarkus-run.jar" "$@"
fi
if [ -f "$POLARIS_HOME/polaris-quarkus-admin.jar" ]; then
  exec java -jar "$POLARIS_HOME/polaris-quarkus-admin.jar" "$@"
fi
echo "ERROR: Polaris admin jar not found under $POLARIS_HOME" >&2
exit 1
SCRIPT

cat > "$BIN_DIR/server" << 'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POLARIS_HOME="$(dirname "$SCRIPT_DIR")"
if [ -f "$POLARIS_HOME/server/quarkus-run.jar" ]; then
  exec java -jar "$POLARIS_HOME/server/quarkus-run.jar" "$@"
fi
if [ -f "$POLARIS_HOME/polaris-quarkus-server.jar" ]; then
  exec java -jar "$POLARIS_HOME/polaris-quarkus-server.jar" "$@"
fi
echo "ERROR: Polaris server jar not found under $POLARIS_HOME" >&2
exit 1
SCRIPT

chmod +x "$BIN_DIR/admin" "$BIN_DIR/server"

if [ ! -f "$CONF_DIR/application.properties" ]; then
  if [ -f "$ROOT/config/polaris/application.properties" ]; then
    cp "$ROOT/config/polaris/application.properties" "$CONF_DIR/application.properties"
  fi
fi

echo "Polaris wrappers: $BIN_DIR/admin $BIN_DIR/server"
