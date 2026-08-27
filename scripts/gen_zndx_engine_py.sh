#!/usr/bin/env bash
# Generate Python stubs from signals-protocol (the specification).
# Run after protocol submodule bumps. Committed under scripts/generated/.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PROTO_ROOT="$ROOT/components/signals-protocol/proto"
OUT="$ROOT/scripts/generated"
mkdir -p "$OUT"
uv run python -m grpc_tools.protoc \
  -I "$PROTO_ROOT" \
  --python_out="$OUT" \
  --grpc_python_out="$OUT" \
  --pyi_out="$OUT" \
  "$PROTO_ROOT/zndx/engine/v1/engine.proto" \
  "$PROTO_ROOT/zndx/scheduler/v1/scheduler.proto"
# Package markers + relative import for in-tree use
touch "$OUT/__init__.py" \
  "$OUT/zndx/__init__.py" \
  "$OUT/zndx/engine/__init__.py" \
  "$OUT/zndx/engine/v1/__init__.py" \
  "$OUT/zndx/scheduler/__init__.py" \
  "$OUT/zndx/scheduler/v1/__init__.py"
sed -i 's/^from zndx\.engine\.v1 import engine_pb2/from . import engine_pb2/' \
  "$OUT/zndx/engine/v1/engine_pb2_grpc.py"
sed -i 's/^from zndx\.scheduler\.v1 import scheduler_pb2/from . import scheduler_pb2/' \
  "$OUT/zndx/scheduler/v1/scheduler_pb2_grpc.py"
sed -i 's/^from zndx\.engine\.v1 import engine_pb2 as /from ...engine.v1 import engine_pb2 as /' \
  "$OUT/zndx/scheduler/v1/scheduler_pb2.py"
sed -i 's/^from zndx\.engine\.v1 import engine_pb2 as /from ...engine.v1 import engine_pb2 as /' \
  "$OUT/zndx/scheduler/v1/scheduler_pb2.pyi"
# Drop leftover unpublished yunikorn stubs if present
rm -rf "$OUT/zndx/yunikorn"
# Mirror into the engine package for runtime imports
ENGINE_GEN="$ROOT/src/signals/engine/generated"
rm -rf "$ENGINE_GEN"
mkdir -p "$ENGINE_GEN"
cp -a "$OUT/." "$ENGINE_GEN/"
echo "gen-zndx-engine-py: wrote $OUT/zndx/engine/v1/ + $OUT/zndx/scheduler/v1/"
echo "gen-zndx-engine-py: mirrored to $ENGINE_GEN"
