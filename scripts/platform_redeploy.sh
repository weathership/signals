#!/usr/bin/env bash
# Thin wrapper — the procedure is src/signals/ops (FSM + Brier ledger).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
exec uv run python -m signals.ops redeploy
