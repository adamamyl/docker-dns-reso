#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'
set -x

#######################################
# Globals / defaults
#######################################
SCRIPT_NAME="$(basename "$0")"
TIMESTAMP="$(date +"%Y%m%d-%H%M%S")"
LOG_DIR="${LOG_DIR:-./logs}"
LOG_FILE=""
SYMLINK_NAME="latest-net.log"

DRY_RUN=false
VERBOSE=false
FORCE=false
MODULE="all"

DNSMASQ_DOMAIN="internal"
DNSMASQ_IP="127.0.0.1"
DNSMASQ_PORT="53"

BREW_PREFIX=""
DNSMASQ_BIN=""

# Summary storage
SUMMARY_SCENARIOS=()
SUMMARY_DNSMASQ_INTENT=()
SUMMARY_DNSMASQ_RUNNING=()
SUMMARY_DIG_RESULT=()
SUMMARY_RESOLVER_COUNT=()

#######################################
# Logging helpers
#######################################
log_ts() {
  date +"%H:%M:%S"
}

log_info() {
  echo "🟢 [INFO] $(log_ts) $*" | tee -a "$LOG_FILE"
}

log_warn() {
  echo "🟡 [WARN] $(log_ts) $*" | tee -a "$LOG_FILE"
}

log_error() {
  echo -e "\a🔴 [ERROR] $(log_ts) $*" | tee -a "$LOG_FILE" >&2
}

#######################################
# Usage
#######################################
usage() {
  cat <<EOF
Usage: $SCRIPT_NAME [options]

Options:
  --dry-run        Show actions without changing state
  --verbose        Extra logging
  --force          Skip interactive prompts
  --module <name>  Run single module (dnsmasq|all)
  --help           Show this help
EOF
}

#######################################
# CLI parsing
#######################################
parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run) DRY_RUN=true ;;
      --verbose) VERBOSE=true ;;
      --force) FORCE=true ;;
      --module)
        MODULE="${2:-}"
        shift
        ;;
      --help)
        usage
        exit 0
        ;;
      *)
        log_error "Unknown argument: $1"
        usage
        exit 1
        ;;
    esac
    shift
  done
}

#######################################
# Dependency checks
#######################################
require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    log_error "Missing required command: $cmd"
    exit 1
  fi
}

detect_brew() {
  if command -v brew >/dev/null 2>&1; then
    BREW_PREFIX="$(brew --prefix)"
  else
    log_error "Homebrew not found (required for dnsmasq)"
    exit 1
  fi
}

detect_dnsmasq() {
  DNSMASQ_BIN="$BREW_PREFIX/opt/dnsmasq/sbin/dnsmasq"
  if [[ ! -x "$DNSMASQ_BIN" ]]; then
    log_error "dnsmasq not found at $DNSMASQ_BIN"
    exit 1
  fi
}

#######################################
# Logging setup
#######################################
init_logging() {
  mkdir -p "$LOG_DIR"
  LOG_FILE="$LOG_DIR/network_test.$TIMESTAMP.log"
  : >"$LOG_FILE"

  if [[ -L "$SYMLINK_NAME" || -e "$SYMLINK_NAME" ]]; then
    rm -f "$SYMLINK_NAME"
  fi
  ln -s "$LOG_FILE" "$SYMLINK_NAME"

  log_info "Log file: $LOG_FILE"
  log_info "CLI flags: DRY_RUN=$DRY_RUN VERBOSE=$VERBOSE FORCE=$FORCE MODULE=$MODULE"
}

#######################################
# Snapshot helpers
#######################################
snapshot_dns() {
  local label="$1"
  log_info "Snapshot DNS ($label)"
  {
    echo "### /etc/resolv.conf"
    cat /etc/resolv.conf
    echo
    echo "### scutil --dns"
    scutil --dns
  } >>"$LOG_FILE" 2>&1
}

snapshot_routes() {
  local label="$1"
  log_info "Snapshot routes ($label)"
  netstat -rn -f inet >>"$LOG_FILE" 2>&1
}

snapshot_ifaces() {
  local label="$1"
  log_info "Snapshot interfaces ($label)"
  ifconfig >>"$LOG_FILE" 2>&1
}

#######################################
# dnsmasq module
#######################################
dnsmasq_conf_dir() {
  echo "$BREW_PREFIX/etc/dnsmasq.d"
}

dnsmasq_conf_file() {
  echo "$(dnsmasq_conf_dir)/network_test.conf"
}

dnsmasq_running() {
  pgrep -f "$DNSMASQ_BIN" >/dev/null 2>&1
}

dnsmasq_start() {
  log_info "Starting dnsmasq"
  if dnsmasq_running; then
    log_warn "dnsmasq already running"
    return
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    log_info "[dry-run] Would start dnsmasq"
    return
  fi

  sudo "$DNSMASQ_BIN" --conf-file="$(dnsmasq_conf_file)" --keep-in-foreground &
  sleep 2
}

dnsmasq_stop() {
  log_info "Stopping dnsmasq"
  if ! dnsmasq_running; then
    log_warn "dnsmasq not running"
    return
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    log_info "[dry-run] Would stop dnsmasq"
    return
  fi

  sudo pkill -f "$DNSMASQ_BIN"
  sleep 1
}

dnsmasq_write_conf() {
  log_info "Writing dnsmasq config"

  if [[ "$DRY_RUN" == "true" ]]; then
    log_info "[dry-run] Would write dnsmasq config"
    return
  fi

  sudo mkdir -p "$(dnsmasq_conf_dir)"
  sudo tee "$(dnsmasq_conf_file)" >/dev/null <<EOF
port=$DNSMASQ_PORT
listen-address=$DNSMASQ_IP
bind-interfaces
domain=$DNSMASQ_DOMAIN
EOF
}

#######################################
# Test helpers
#######################################
count_resolvers() {
  scutil --dns | grep -c '^resolver'
}

dnsmasq_test_dig() {
  if dig @"$DNSMASQ_IP" localhost >/dev/null 2>&1; then
    echo "ok"
  else
    echo "fail"
  fi
}

#######################################
# Scenario runner
#######################################
run_scenario() {
  local name="$1"
  local dnsmasq_enabled="$2"

  log_info "=== Scenario: $name ==="

  snapshot_dns "before-$name"
  snapshot_routes "before-$name"
  snapshot_ifaces "before-$name"

  if [[ "$dnsmasq_enabled" == "true" ]]; then
    dnsmasq_write_conf
    dnsmasq_start
  else
    dnsmasq_stop
  fi

  snapshot_dns "after-$name"

  # Collect summary data
  SUMMARY_SCENARIOS+=("$name")
  SUMMARY_DNSMASQ_INTENT+=("$dnsmasq_enabled")

  if dnsmasq_running; then
    SUMMARY_DNSMASQ_RUNNING+=("yes")
  else
    SUMMARY_DNSMASQ_RUNNING+=("no")
  fi

  SUMMARY_DIG_RESULT+=("$(dnsmasq_test_dig)")
  SUMMARY_RESOLVER_COUNT+=("$(count_resolvers)")

  if [[ "$dnsmasq_enabled" == "true" ]]; then
    dnsmasq_stop
  fi
}

#######################################
# Summary
#######################################
print_summary() {
  log_info "=== Summary ==="
  printf "\n%-22s %-10s %-16s %-10s %-15s\n" \
    "Scenario" "dnsmasq" "running" "dig" "resolvers" \
    | tee -a "$LOG_FILE"

  local i
  for ((i=0; i<${#SUMMARY_SCENARIOS[@]}; i++)); do
    printf "%-22s %-10s %-16s %-10s %-15s\n" \
      "${SUMMARY_SCENARIOS[$i]}" \
      "${SUMMARY_DNSMASQ_INTENT[$i]}" \
      "${SUMMARY_DNSMASQ_RUNNING[$i]}" \
      "${SUMMARY_DIG_RESULT[$i]}" \
      "${SUMMARY_RESOLVER_COUNT[$i]}" \
      | tee -a "$LOG_FILE"
  done
}

#######################################
# Main
#######################################
main() {
  parse_args "$@"

  require_cmd dig
  require_cmd netstat
  require_cmd ifconfig
  require_cmd scutil
  require_cmd sudo

  detect_brew
  detect_dnsmasq
  init_logging

  log_info "=== Network DNS Test (dnsmasq focus) ==="

  run_scenario "baseline-no-dnsmasq" "false"
  run_scenario "with-dnsmasq" "true"

  print_summary
  log_info "Test complete"
}

main "$@"
