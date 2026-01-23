#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'
set -x

# ============================================================
# Configuration / Defaults
# ============================================================

SCRIPT_NAME="$(basename "$0")"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="./network_test.${TIMESTAMP}.log"
SYMLINK="./latest-net.log"

DRY_RUN=false
VERBOSE=false
FORCE=false
MODULE="all"

DOCKER_IMAGE="nginx:alpine"
DOCKER_CONTAINER=""
BREW_PREFIX="$(brew --prefix 2>/dev/null || true)"

TMPDIR="$(mktemp -d "/tmp/network_test.XXXXXX")"

declare -A SCENARIO_SUMMARY=()

# ============================================================
# Logging (NO function named `log`)
# ============================================================

_ts() { date +"%Y-%m-%d %H:%M:%S"; }

log_info() { echo "🟢 [INFO] $(_ts) $*" | tee -a "$LOG_FILE"; }
log_warn() { echo "⚠️  [WARN] $(_ts) $*" | tee -a "$LOG_FILE"; }
log_ok()   { echo "✅ [OK]   $(_ts) $*" | tee -a "$LOG_FILE"; }
log_err()  { echo "❌ [ERR]  $(_ts) $*" | tee -a "$LOG_FILE" >&2; }

run_cmd() {
  if [[ "$DRY_RUN" == true ]]; then
    log_info "[dry-run] $*"
  else
    "$@"
  fi
}

# ============================================================
# Cleanup
# ============================================================

cleanup() {
  rm -rf "$TMPDIR"
}
trap cleanup EXIT

# ============================================================
# CLI parsing
# ============================================================

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME [options]

Options:
  --dry-run        Log actions without changing anything
  --verbose        Extra logging
  --force          Skip prompts
  --module NAME    Run a single module
                   (docker|dnsmasq|tailscale|nordvpn|scenario)
  --help           Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true ;;
    --verbose) VERBOSE=true ;;
    --force) FORCE=true ;;
    --module) MODULE="$2"; shift ;;
    --help) usage; exit 0 ;;
    *) log_err "Unknown argument: $1"; usage; exit 1 ;;
  esac
  shift
done

# ============================================================
# Logfile + symlink setup
# ============================================================

touch "$LOG_FILE"

if [[ -L "$SYMLINK" || -e "$SYMLINK" ]]; then
  rm -f "$SYMLINK"
fi
ln -s "$LOG_FILE" "$SYMLINK"

log_info "Log file: $LOG_FILE"
log_info "Symlink : $SYMLINK"

log_info "CLI flags: DRY_RUN=$DRY_RUN VERBOSE=$VERBOSE FORCE=$FORCE MODULE=$MODULE"

# ============================================================
# Dependency checks
# ============================================================

require_bin() {
  command -v "$1" >/dev/null 2>&1 || {
    log_err "Missing dependency: $1"
    exit 1
  }
}

require_bin docker
require_bin dig
require_bin ping
require_bin netstat
require_bin ifconfig

# ============================================================
# NordVPN detection (GUI app only)
# ============================================================

nordvpn_running() {
  pgrep -f "/Applications/NordVPN.app/Contents/MacOS/NordVPN" >/dev/null 2>&1
}

start_nordvpn() {
  if nordvpn_running; then
    log_ok "NordVPN already running"
  else
    log_warn "NordVPN not running — please start it manually"
    open -a "NordVPN" || true
    read -rp "Press Enter once NordVPN is connected..."
  fi
}

stop_nordvpn() {
  if nordvpn_running; then
    log_warn "Please disconnect NordVPN manually"
    read -rp "Press Enter once NordVPN is stopped..."
  else
    log_ok "NordVPN already stopped"
  fi
}

# ============================================================
# Tailscale
# ============================================================

tailscale_running() {
  pgrep -f tailscaled >/dev/null 2>&1
}

start_tailscale() {
  if tailscale_running; then
    log_ok "Tailscale already running"
  else
    log_warn "Starting Tailscale"
    run_cmd tailscale up || true
  fi
}

stop_tailscale() {
  if tailscale_running; then
    log_warn "Stopping Tailscale"
    run_cmd tailscale down || true
  else
    log_ok "Tailscale already stopped"
  fi
}

# ============================================================
# Docker container
# ============================================================

random_name() {
  shuf -n2 /usr/share/dict/words 2>/dev/null | tr '\n' '-' | sed 's/-$//'
}

start_docker_container() {
  DOCKER_CONTAINER="$(random_name)"
  log_info "Starting test container: $DOCKER_CONTAINER"

  run_cmd docker run -d \
    --name "$DOCKER_CONTAINER" \
    --rm \
    "$DOCKER_IMAGE" \
    sleep 1d
}

stop_docker_container() {
  if [[ -n "$DOCKER_CONTAINER" ]]; then
    run_cmd docker rm -f "$DOCKER_CONTAINER" || true
  fi
}

docker_ip() {
  docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$DOCKER_CONTAINER"
}

# ============================================================
# Routes capture
# ============================================================

capture_routes() {
  local file="$1"
  netstat -rn -f inet >"$file"
}

diff_routes() {
  local before="$1"
  local after="$2"
  log_info "Route diff:"
  diff -u "$before" "$after" | tee -a "$LOG_FILE" || true
}

# ============================================================
# Scenario runner
# ============================================================

add_summary() {
  local scenario="$1"
  local msg="$2"
  SCENARIO_SUMMARY["$scenario"]+="$msg; "
}

run_scenario() {
  local name="$1"
  local ts="$2"
  local vpn="$3"

  log_info "=== Scenario: $name ==="

  local before="$TMPDIR/routes_before_$name"
  local after="$TMPDIR/routes_after_$name"

  capture_routes "$before"

  [[ "$ts" == start ]] && start_tailscale
  [[ "$ts" == stop ]] && stop_tailscale
  [[ "$vpn" == start ]] && start_nordvpn
  [[ "$vpn" == stop ]] && stop_nordvpn

  capture_routes "$after"
  diff_routes "$before" "$after"

  local ip
  ip="$(docker_ip)"

  if ping -c2 "$ip" >/dev/null 2>&1; then
    add_summary "$name" "docker ping OK"
  else
    add_summary "$name" "docker ping FAIL"
  fi
}

# ============================================================
# Main execution
# ============================================================

log_info "=== Docker + Tailscale + VPN Network Test ==="

if [[ "$MODULE" == "all" || "$MODULE" == "docker" ]]; then
  start_docker_container
fi

if [[ "$MODULE" == "all" || "$MODULE" == "scenario" ]]; then
  run_scenario "none" stop stop
  run_scenario "tailscale-only" start stop
  run_scenario "nordvpn-only" stop start
  run_scenario "both" start start
fi

if [[ "$MODULE" == "all" || "$MODULE" == "docker" ]]; then
  stop_docker_container
fi

# ============================================================
# Summary
# ============================================================

log_info "=== Summary ==="
for k in "${!SCENARIO_SUMMARY[@]}"; do
  echo "📌 $k: ${SCENARIO_SUMMARY[$k]}" | tee -a "$LOG_FILE"
done

log_ok "Done."
