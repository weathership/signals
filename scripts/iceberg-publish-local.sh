#!/usr/bin/env bash
# Publish Signals Iceberg (FileFormat.HDF5) + iceberg-hdf5 into SIG_MAVEN_REPO.
# Then Impala FE/runtime resolve 1.11.0-signals-hdf5 from mavenLocal, not Central.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export JAVA_HOME="${JAVA_HOME:-$HOME/local/src/wxs/signals/.devenv/profile}"
export PATH="$JAVA_HOME/bin:${PATH:-}"
ICEBERG="$ROOT/components/iceberg"
REPO="${SIG_MAVEN_REPO:-$ROOT/.devenv/m2}"
VER="$(tr -d '[:space:]' < "$ICEBERG/version.txt")"
mkdir -p "$REPO"
echo "Publishing Iceberg $VER → $REPO"
cd "$ICEBERG"
./gradlew :iceberg-api:publishToMavenLocal \
  :iceberg-core:publishToMavenLocal \
  :iceberg-common:publishToMavenLocal \
  :iceberg-bundled-guava:publishToMavenLocal \
  :iceberg-data:publishToMavenLocal \
  :iceberg-parquet:publishToMavenLocal \
  :iceberg-hive-metastore:publishToMavenLocal \
  :iceberg-mr:publishToMavenLocal \
  -x test -x javadoc -x spotlessCheck \
  -Dmaven.repo.local="$REPO"

SEMANTICS="${SEMANTICS_HOME:-$HOME/local/src/zndx/gaius/external/semantics}"
echo "Installing iceberg-hdf5 (jhdf FormatModel) from $SEMANTICS"
mvn -f "$SEMANTICS/java/iceberg-hdf5/pom.xml" install -DskipTests \
  -Diceberg.version="$VER" \
  -Danalog.fixture="$SEMANTICS/analog/fixtures/sdg_machine_small.h5" \
  -Dmaven.repo.local="$REPO"

echo "OK Iceberg $VER + org.zndx.semantics:iceberg-hdf5 in $REPO"
echo "Rebuild Impala: scripts/impala-build-isolated.sh (or devenv tasks run impala:build)"
