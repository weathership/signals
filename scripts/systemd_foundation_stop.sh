#!/usr/bin/env bash
# Lattice-safe foundation stop for signals.service (systemd).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="/usr/local/bin:/usr/bin:/bin:${HOME}/.nix-profile/bin:${PATH:-}"

echo "systemd-foundation: just down"
just down || true
