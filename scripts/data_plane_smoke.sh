#!/usr/bin/env bash
# One-off wrapper → elevated CI gate. Prefer: just data-plane-ci
# Kept for local/ad-hoc use under ./scripts/ (smoke naming).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "data-plane-smoke: delegating to data_plane_ci.sh (elevated gate is CI)" >&2
exec bash "$ROOT/scripts/data_plane_ci.sh" "$@"
