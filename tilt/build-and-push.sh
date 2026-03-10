#!/usr/bin/env bash
# Build and push container image for Tilt live_update
# Usage: build-and-push.sh <expected-ref>
set -euo pipefail

EXPECTED_REF="$1"

# Build with podman
podman build -t "$EXPECTED_REF" -f Dockerfile .

# Push to local registry
podman push "$EXPECTED_REF"
