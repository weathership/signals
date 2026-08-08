#!/usr/bin/env bash
# Seed atlas.* Kudu projection tables via Impala HS2 and register PG foreign tables.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HS2_SQL="${HS2_SQL:-/tmp/hs2_sql}"
DDL="$ROOT/config/atlas/kudu_projections.sql"
FDW_SQL="$ROOT/config/atlas/kudu_projections_fdw.sql"
PGHOST="${PGHOST:-127.0.0.1}"
PGPORT="${PGPORT:-5455}"
PGDATABASE="${PGDATABASE:-signals}"

if [[ ! -x "$HS2_SQL" ]]; then
  echo "ERROR: need executable HS2 client at HS2_SQL=$HS2_SQL"
  echo "  (e.g. rebuild /tmp/hs2_sql from components/impala_fdw after devenv thrift build)"
  exit 1
fi

# Strip -- comments; split on ';'
mapfile -t STMTS < <(python3 - "$DDL" <<'PY'
import sys, re
text = open(sys.argv[1]).read()
lines = []
for line in text.splitlines():
    if line.strip().startswith("--") or not line.strip():
        continue
    lines.append(line)
body = "\n".join(lines)
for part in body.split(";"):
    stmt = " ".join(part.split())
    if stmt:
        print(stmt)
PY
)

for stmt in "${STMTS[@]}"; do
  echo ">>> ${stmt:0:100}..."
  if ! "$HS2_SQL" "$stmt" 2>&1; then
    echo "WARN: statement failed (continuing): ${stmt:0:80}" >&2
  fi
done

echo "=== Register foreign tables on $PGHOST:$PGPORT/$PGDATABASE ==="
psql -h "$PGHOST" -p "$PGPORT" -d "$PGDATABASE" -v ON_ERROR_STOP=1 -f "$FDW_SQL"
echo "OK: atlas Kudu projections + foreign tables"
