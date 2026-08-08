#!/usr/bin/env bash
# After zarf package deploy, digest-only pushes may lack tags that the Zarf agent
# and Helm charts expect. Retag linux/amd64 digests in the local Zarf registry.
# Usage: ./scripts/retag-registry-tags.sh
set -euo pipefail
REG="${ZARF_REGISTRY:-127.0.0.1:31999}"
USER="${ZARF_PUSH_USER:-zarf-push}"
PASS="${ZARF_PUSH_PASS:-$(zarf tools get-creds registry 2>/dev/null | tail -1)}"

podman login --tls-verify=false -u "$USER" -p "$PASS" "$REG"

retag() {
  local digest="$1" tag="$2" repo="$3"
  local src="${REG}/${repo}@sha256:${digest}"
  echo "retag ${repo}@${digest:0:12} -> ${tag}"
  podman pull --tls-verify=false "$src"
  podman tag "$src" "${REG}/${repo}:${tag}"
  podman push --tls-verify=false "${REG}/${repo}:${tag}"
}

# From BOOTSTRAP_VERSIONS.txt (keep in sync)
retag f72beb424e109f758fcb173b3425ddba3ff78288cd6a596f3037e28c2816573b scheduler-1.9.0 apache/yunikorn
retag d6b5c51578e5b658a525456bf1c747d5bb8cced0ba9f1cb596d1997892c8cdb2 web-1.9.0 apache/yunikorn
retag f3d04f501324c46f2cb5baea6eb2b7ddaddd49a4b8d0d4592625742b83f294cb admission-1.9.0 apache/yunikorn
retag 6dbee417fd7657524bb8e4571eb5e886367437a77b932df29e115c88c4d07874 0.99.2 apache/nifi-minifi-cpp

echo "done"
