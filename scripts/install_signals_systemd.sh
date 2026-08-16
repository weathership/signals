#!/usr/bin/env bash
# Install foundation (+ optional peer) systemd units from infra/systemd/.
#
# Usage:
#   scripts/install_signals_systemd.sh              # foundation only
#   scripts/install_signals_systemd.sh --peers      # foundation + all peer samples
#   scripts/install_signals_systemd.sh --peers gaius,metabase
#   scripts/install_signals_systemd.sh --enable      # systemctl enable after install
#   scripts/install_signals_systemd.sh --start       # enable + start signals.target
#
# Requires sudo for /etc/systemd/system.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="$ROOT/infra/systemd"
DEST="${SIGNALS_SYSTEMD_DEST:-/etc/systemd/system}"

DO_PEERS=0
PEER_CSV=""
DO_ENABLE=0
DO_START=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --peers)
      DO_PEERS=1
      if [[ -n "${2:-}" && "$2" != --* ]]; then
        PEER_CSV="$2"
        shift
      fi
      ;;
    --enable) DO_ENABLE=1 ;;
    --start) DO_ENABLE=1; DO_START=1 ;;
    -h|--help)
      sed -n '2,16p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

info() { echo "install-systemd: $*"; }
die() { echo "ERROR: install-systemd: $*" >&2; exit 1; }

[[ -d "$UNIT_DIR" ]] || die "missing $UNIT_DIR"
command -v sudo >/dev/null || die "sudo required"

FOUNDATION=(signals.target signals.service signals-ready.service signals-engine.service signals-c2.service signals-polaris.service)
UNITS=("${FOUNDATION[@]}")

if [[ "$DO_PEERS" == "1" ]]; then
  if [[ -n "$PEER_CSV" ]]; then
    IFS=',' read -ra ids <<<"$PEER_CSV"
    for id in "${ids[@]}"; do
      id="$(echo "$id" | tr -d '[:space:]')"
      [[ -f "$UNIT_DIR/${id}.service" ]] || die "no unit sample for $id"
      UNITS+=("${id}.service")
    done
  else
    for f in aegir atelier gaius synth metabase; do
      UNITS+=("${f}.service")
    done
  fi
fi

info "installing to $DEST: ${UNITS[*]}"
for u in "${UNITS[@]}"; do
  sudo install -m 644 "$UNIT_DIR/$u" "$DEST/$u"
done

sudo systemctl daemon-reload
info "daemon-reload OK"

if [[ "$DO_ENABLE" == "1" ]]; then
  sudo systemctl enable "${UNITS[@]}"
  info "enabled: ${UNITS[*]}"
fi

if [[ "$DO_START" == "1" ]]; then
  info "starting signals.target (foundation + enabled peers)…"
  # If stack already up via devenv, signals.service just up is idempotent
  sudo systemctl start signals.target
  systemctl --no-pager --full status signals.service signals-ready.service || true
  info "status signals-ready: $(systemctl is-active signals-ready.service 2>/dev/null || echo unknown)"
fi

info "done"
info "  lattice: just lattice-ci"
info "  ready:   just signals-ready"
