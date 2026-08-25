#!/usr/bin/env bash
# Compile (if stale) and run IcebergHdf5Register against the Impala package
# classpath, which already carries the signals Iceberg fork, iceberg-hdf5,
# jhdf and hadoop-aws. Guru: #SL.00000025.TIERUP
#
#   scripts/iceberg_hdf5_register.sh <table> <epoch_hour> <s3a-path> <size> <records> [local-h5]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CP_FILE="$ROOT/components/impala/java/impala-package/target/package-classpath.txt"
[ -s "$CP_FILE" ] || { echo "ERROR: $CP_FILE missing — devenv tasks run impala:build-fe" >&2; exit 1; }
CP="$(cat "$CP_FILE")"
OUT="$ROOT/.devenv/bin/iceberg-register"
SRC="$ROOT/scripts/IcebergHdf5Register.java"
mkdir -p "$OUT"
if [ ! -f "$OUT/IcebergHdf5Register.class" ] || [ "$SRC" -nt "$OUT/IcebergHdf5Register.class" ]; then
  javac -d "$OUT" -cp "$CP" "$SRC"
fi
exec java -cp "$OUT:$CP" IcebergHdf5Register "$@"
