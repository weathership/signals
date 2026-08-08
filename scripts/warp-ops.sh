#!/usr/bin/env bash
# just warp — Cloudflare WARP / Zero Trust client operations
#
# Verifies current state, then asks about connect/disconnect and package upgrade.
# Never connects or upgrades without an explicit yes.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ok()   { echo "  ✓ $*"; }
bad()  { echo "  ✗ $*"; }
note() { echo "  · $*"; }
warn() { echo "  ! $*"; }

need_warp_cli() {
  if ! command -v warp-cli >/dev/null 2>&1; then
    bad "warp-cli not on PATH"
    echo "  Install: https://pkg.cloudflareclient.com/ (cloudflare-warp package)"
    exit 1
  fi
}

warp_trace_field() {
  local key="$1"
  curl -sS -m 8 https://www.cloudflare.com/cdn-cgi/trace 2>/dev/null \
    | awk -F= -v k="$key" '$1==k {print $2; exit}'
}

print_status() {
  echo "════════════════════════════════════════════════════════════"
  echo " Cloudflare WARP / Zero Trust — client state"
  echo "════════════════════════════════════════════════════════════"

  need_warp_cli
  local ver status_line reason
  ver=$(warp-cli --version 2>/dev/null | head -1 || echo "unknown")
  ok "warp-cli: $ver"

  # Daemon
  if systemctl is-active --quiet warp-svc 2>/dev/null \
    || systemctl is-active --quiet warp-svc.service 2>/dev/null; then
    ok "warp-svc: active (systemd)"
    systemctl show warp-svc -p ActiveEnterTimestamp --value 2>/dev/null \
      | sed 's/^/    since /' || true
  else
    bad "warp-svc: not active — client cannot connect until the daemon runs"
    note "try: sudo systemctl enable --now warp-svc"
  fi

  # Registration / org
  if warp-cli registration show >/dev/null 2>&1; then
    ok "registration:"
    warp-cli registration show 2>/dev/null | sed 's/^/    /'
  else
    warn "registration: not shown (device may need re-enroll into org)"
  fi

  # Connection status (match Disconnected before Connected — substring trap)
  status_line=$(warp-cli status 2>&1 || true)
  echo "  status:"
  echo "$status_line" | sed 's/^/    /'
  if echo "$status_line" | grep -qiE 'Status update:[[:space:]]*Disconnected|status:[[:space:]]*Disconnected'; then
    bad "tunnel: Disconnected"
    reason=$(echo "$status_line" | grep -i 'Reason:' | sed 's/^[[:space:]]*//' || true)
    [ -n "${reason:-}" ] && note "$reason"
  elif echo "$status_line" | grep -qiE 'Status update:[[:space:]]*Connected|status:[[:space:]]*Connected'; then
    ok "tunnel: Connected"
  else
    warn "tunnel: unexpected status (see above)"
  fi

  # Settings snapshot (subset)
  if warp-cli settings >/dev/null 2>&1; then
    note "settings (excerpt):"
    warp-cli settings 2>/dev/null \
      | grep -iE 'Always On|Mode:|Organization|Include mode|WARP tunnel|Allow Updates' \
      | sed 's/^/    /' || true
  fi

  # Live edge truth
  local warp_flag gateway_flag colo ip
  warp_flag=$(warp_trace_field warp || echo "?")
  gateway_flag=$(warp_trace_field gateway || echo "?")
  colo=$(warp_trace_field colo || echo "?")
  ip=$(warp_trace_field ip || echo "?")
  if [ "$warp_flag" = "on" ]; then
    ok "cdn-cgi/trace: warp=$warp_flag gateway=$gateway_flag colo=$colo"
  else
    bad "cdn-cgi/trace: warp=${warp_flag:-off} gateway=${gateway_flag:-off} colo=$colo"
  fi
  note "egress ip: $ip"

  # Package version vs candidate
  WARP_UPGRADE_AVAILABLE=0
  WARP_INSTALLED="unknown"
  WARP_CANDIDATE="unknown"
  if command -v apt-cache >/dev/null 2>&1 && dpkg -l cloudflare-warp >/dev/null 2>&1; then
    local installed candidate policy
    policy=$(apt-cache policy cloudflare-warp 2>/dev/null || true)
    installed=$(printf '%s\n' "$policy" | awk '/Installed:/ {print $2; exit}')
    candidate=$(printf '%s\n' "$policy" | awk '/Candidate:/ {print $2; exit}')
    WARP_INSTALLED="${installed:-unknown}"
    WARP_CANDIDATE="${candidate:-unknown}"
    echo "  package:"
    echo "    installed: $WARP_INSTALLED"
    echo "    candidate: $WARP_CANDIDATE"
    if [ -n "$installed" ] && [ -n "$candidate" ] && [ "$installed" != "$candidate" ] \
      && [ "$candidate" != "(none)" ]; then
      warn "upgrade available: $installed → $candidate"
      WARP_UPGRADE_AVAILABLE=1
    else
      ok "package at candidate (or no newer candidate visible)"
    fi
  else
    note "apt policy unavailable — skip package version compare"
  fi

  # cloudflared (tunnel CLI — separate from WARP desktop client)
  if command -v cloudflared >/dev/null 2>&1; then
    note "cloudflared also on PATH: $(cloudflared --version 2>&1 | head -1)"
  fi

  echo "════════════════════════════════════════════════════════════"
}

ask_yes_no() {
  local prompt="$1" default="${2:-n}"
  local hint yn
  if [ "$default" = "y" ]; then hint="[Y/n]"; else hint="[y/N]"; fi
  read -r -p "$prompt $hint " yn || true
  yn=${yn:-$default}
  case "$yn" in
    y|Y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

do_connect() {
  need_warp_cli
  echo "→ warp-cli connect"
  if warp-cli connect; then
    sleep 2
    warp-cli status 2>&1 | sed 's/^/  /'
    local w
    w=$(warp_trace_field warp || echo off)
    if [ "$w" = "on" ]; then
      ok "connected (trace warp=on)"
    else
      warn "connect issued but trace still warp=$w — wait a few seconds or check org policy"
    fi
  else
    bad "warp-cli connect failed"
    return 1
  fi
}

do_disconnect() {
  need_warp_cli
  echo "→ warp-cli disconnect"
  warp-cli disconnect
  sleep 1
  warp-cli status 2>&1 | sed 's/^/  /'
}

# Refresh WARP_INSTALLED / WARP_CANDIDATE / WARP_UPGRADE_AVAILABLE from apt.
refresh_package_info() {
  WARP_UPGRADE_AVAILABLE=0
  WARP_INSTALLED="unknown"
  WARP_CANDIDATE="unknown"
  command -v apt-cache >/dev/null 2>&1 || return 0
  dpkg -l cloudflare-warp >/dev/null 2>&1 || return 0
  local policy
  policy=$(apt-cache policy cloudflare-warp 2>/dev/null || true)
  WARP_INSTALLED=$(printf '%s\n' "$policy" | awk '/Installed:/ {print $2; exit}')
  WARP_CANDIDATE=$(printf '%s\n' "$policy" | awk '/Candidate:/ {print $2; exit}')
  WARP_INSTALLED=${WARP_INSTALLED:-unknown}
  WARP_CANDIDATE=${WARP_CANDIDATE:-unknown}
  if [ "$WARP_INSTALLED" != "unknown" ] && [ "$WARP_CANDIDATE" != "unknown" ] \
    && [ "$WARP_INSTALLED" != "$WARP_CANDIDATE" ] && [ "$WARP_CANDIDATE" != "(none)" ]; then
    WARP_UPGRADE_AVAILABLE=1
  fi
}

# $1 = auto | force
#   auto  — only-upgrade when candidate > installed; no-op if already current
#   force — apt update + install/reinstall even when already at candidate
do_upgrade() {
  local mode="${1:-auto}"
  refresh_package_info

  if [ "$mode" = "auto" ] && [ "${WARP_UPGRADE_AVAILABLE:-0}" != "1" ]; then
    note "no package upgrade detected (installed=$WARP_INSTALLED candidate=$WARP_CANDIDATE); nothing to do"
    note "use force reinstall from interactive menu, or: just warp upgrade --force"
    return 0
  fi

  local apt_cmd=()
  if [ "$(id -u)" -eq 0 ]; then
    apt_cmd=(apt-get)
  elif command -v sudo >/dev/null 2>&1; then
    apt_cmd=(sudo apt-get)
  else
    bad "need root or sudo to upgrade the package"
    note "run: sudo apt update && sudo apt install --only-upgrade cloudflare-warp"
    return 1
  fi

  echo "→ apt update (cloudflare-warp maintenance)"
  # Do not let apt soft failures kill the script under set -e
  set +e
  "${apt_cmd[@]}" update -qq
  local upd_rc=$?
  set -e
  if [ "$upd_rc" -ne 0 ]; then
    warn "apt update exited $upd_rc — continuing with cached package lists"
  fi
  refresh_package_info

  local install_rc=0
  if [ "$mode" = "force" ]; then
    echo "→ force install/reinstall cloudflare-warp (installed=$WARP_INSTALLED candidate=$WARP_CANDIDATE)"
    set +e
    if [ "$WARP_INSTALLED" != "unknown" ] && [ "$WARP_INSTALLED" = "$WARP_CANDIDATE" ]; then
      # Already at candidate: reinstall refreshes files without requiring a newer version
      "${apt_cmd[@]}" install -y --reinstall cloudflare-warp
      install_rc=$?
    else
      # Prefer newer candidate when one exists; fall back to reinstall
      "${apt_cmd[@]}" install -y cloudflare-warp
      install_rc=$?
      if [ "$install_rc" -ne 0 ]; then
        "${apt_cmd[@]}" install -y --reinstall cloudflare-warp
        install_rc=$?
      fi
    fi
    set -e
  else
    echo "→ upgrade cloudflare-warp: ${WARP_INSTALLED} → ${WARP_CANDIDATE}"
    set +e
    "${apt_cmd[@]}" install -y --only-upgrade cloudflare-warp
    install_rc=$?
    set -e
  fi

  if [ "$install_rc" -ne 0 ]; then
    bad "apt install cloudflare-warp failed (exit $install_rc)"
    return 1
  fi

  local now
  now=$(warp-cli --version 2>/dev/null | head -1 || echo "unknown")
  ok "package now: $now"
  note "if the daemon was restarted, re-run: just warp  (and connect if needed)"
  return 0
}

do_always_on() {
  local mode="$1"
  if [ "$mode" = "on" ]; then
    echo "→ warp-cli enable-always-on (if supported)"
    warp-cli enable-always-on 2>&1 || warp-cli set-always-on true 2>&1 || {
      warn "could not set Always On via CLI — use the GUI or org policy"
      return 1
    }
  else
    echo "→ warp-cli disable-always-on"
    warp-cli disable-always-on 2>&1 || warp-cli set-always-on false 2>&1 || {
      warn "could not clear Always On via CLI"
      return 1
    }
  fi
}

interactive() {
  export WARP_UPGRADE_AVAILABLE=0
  print_status

  local connected=0 st
  st=$(warp-cli status 2>&1 || true)
  if echo "$st" | grep -qiE 'Status update:[[:space:]]*Connected'; then
    connected=1
  fi

  echo ""
  echo "Forward operations (nothing runs without confirmation)"
  echo ""

  if [ "$connected" -eq 0 ]; then
    if ask_yes_no "Connect WARP now?" "y"; then
      do_connect || true
    else
      note "left disconnected"
    fi
  else
    if ask_yes_no "Disconnect WARP?" "n"; then
      do_disconnect || true
    else
      note "left connected"
    fi
  fi

  echo ""
  if [ "${WARP_UPGRADE_AVAILABLE:-0}" = "1" ]; then
    echo "Maintenance: package upgrade available (${WARP_INSTALLED} → ${WARP_CANDIDATE})."
    if ask_yes_no "Upgrade cloudflare-warp via apt now? (needs sudo)" "n"; then
      do_upgrade auto || true
    else
      note "skipped upgrade — when ready: just warp upgrade"
    fi
  else
    echo "Maintenance: no newer package candidate (installed=$WARP_INSTALLED candidate=$WARP_CANDIDATE)."
    if ask_yes_no "Force apt update + reinstall cloudflare-warp anyway? (needs sudo)" "n"; then
      do_upgrade force || true
    else
      note "skipped force reinstall"
    fi
  fi

  echo ""
  # Always On is often locked by org policy
  local always
  always=$(warp-cli settings 2>/dev/null | grep -i 'Always On' | head -1 || true)
  if echo "$always" | grep -qi 'false'; then
    if ask_yes_no "Enable Always On (reconnect after reboot/sleep)?" "n"; then
      do_always_on on || true
    fi
  elif echo "$always" | grep -qi 'true'; then
    if ask_yes_no "Disable Always On?" "n"; then
      do_always_on off || true
    fi
  fi

  echo ""
  echo "Re-check after changes:"
  print_status

  echo ""
  echo "Tips:"
  note "Org: weathership Zero Trust — include routes cover CF One + *.dev.aws.zndx.org"
  note "Lab Kerberos is separate (just bootstrap); WARP is edge/Zero Trust reachability"
  note "Non-interactive: just warp status | connect | disconnect | upgrade"
  echo "════════════════════════════════════════════════════════════"
}

usage() {
  cat <<EOF
Usage: $(basename "$0") [status|connect|disconnect|upgrade [--force]|interactive|help]

  (default) interactive   Status + questions for connect/disconnect/upgrade
  status                  Verify current WARP state only
  connect                 warp-cli connect
  disconnect              warp-cli disconnect
  upgrade                 apt only-upgrade if candidate newer
  upgrade --force         apt update + reinstall even when already current
  help                    This help

just warp                 → interactive
just warp status          → status only
just warp upgrade --force → forced reinstall path
EOF
}

main() {
  local cmd="${1:-interactive}"
  shift || true
  case "$cmd" in
    status|st) print_status ;;
    connect|on) need_warp_cli; do_connect ;;
    disconnect|off) need_warp_cli; do_disconnect ;;
    upgrade)
      need_warp_cli
      if [ "${1:-}" = "--force" ] || [ "${1:-}" = "force" ]; then
        do_upgrade force
      else
        do_upgrade auto
      fi
      ;;
    interactive|i) interactive ;;
    -h|--help|help) usage ;;
    *) echo "Unknown: $cmd"; usage; exit 2 ;;
  esac
}

main "$@"
