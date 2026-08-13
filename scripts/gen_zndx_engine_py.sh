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
  "$PROTO_ROOT/zndx/engine/v1/engine.proto"
# Package markers + relative import for in-tree use
touch "$OUT/__init__.py" \
  "$OUT/zndx/__init__.py" \
  "$OUT/zndx/engine/__init__.py" \
  "$OUT/zndx/engine/v1/__init__.py"
sed -i 's/^from zndx\.engine\.v1 import engine_pb2/from . import engine_pb2/' \
  "$OUT/zndx/engine/v1/engine_pb2_grpc.py"
echo "gen-zndx-engine-py: wrote $OUT/zndx/engine/v1/"
