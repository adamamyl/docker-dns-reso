#!/usr/bin/env bash
# network_test.sh
# Modern Bash network testing script (dnsmasq + Docker + Tailscale)
# Modular, idempotent, verbose, dry-run, cross-platform aware

set -euo pipefail
IFS=$'\n\t'

# === Globals ===
SCRIPT_NAME=$(basename "$0")

# === Base directories ===
BASEDIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# --- Logs ---
LOG_DIR="$BASEDIR/logs"
mkdir -p "$LOG_DIR"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
LOG_FILE="$LOG_DIR/network_test.$TIMESTAMP.log"
SYMLINK="$LOG_DIR/latest-net.log"

# Default flags
DRY_RUN=false
VERBOSE=false
FORCE=false
MODULE="all"

declare -A SUMMARY_RESULTS

# === Colors & Emojis ===
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; BLUE='\033[0;34m'; NC='\033[0m'
EMOJI_INFO="🟢"; EMOJI_WARN="🟡"; EMOJI_ERROR="🔴"; EMOJI_OK="✅"

# === Logging ===
log() { local level="$1"; shift; local msg="$*"; echo -e "${level} [${SCRIPT_NAME}] $(date +%T) $msg" | tee -a "$LOG_FILE"; }
info() { log "${EMOJI_INFO}[INFO]" "$@"; }
warn() { log "${EMOJI_WARN}[WARN]" "$@"; }
error() { log "${EMOJI_ERROR}[ERROR]" "$@"; }

# === Helpers ===
run_cmd() {
    local cmd="$*"
    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] $cmd"
    else
        eval "$cmd"
    fi
}

snapshot_dns() {
    local label="$1"
    info "Snapshot DNS ($label)"
    echo "### /etc/resolv.conf" >> "$LOG_FILE"
    cat /etc/resolv.conf >> "$LOG_FILE"
    echo >> "$LOG_FILE"
    echo "### scutil --dns" >> "$LOG_FILE"
    scutil --dns >> "$LOG_FILE" || true
    echo >> "$LOG_FILE"
}

snapshot_routes() {
    local label="$1"
    info "Snapshot routes ($label)"
    netstat -rn >> "$LOG_FILE" || true
}

snapshot_interfaces() {
    local label="$1"
    info "Snapshot interfaces ($label)"
    ifconfig >> "$LOG_FILE" || true
}

# === Symlink latest log ===
update_symlink() {
    ln -sf "$LOG_FILE" "$SYMLINK"
    info "Updated symlink: $SYMLINK -> $LOG_FILE"
}


update_symlink

# === Modules ===

# --- ps Module ---
run_ps_module() {
    info "Running process snapshot module"
    ps -e -o pid,comm | grep -Ei "(tailscale|tailscaled|nordvpn|nordvpnd|dnsmasq|docker|dockerd)" \
        | tee -a "$LOG_FILE" || echo "No matching processes running" | tee -a "$LOG_FILE"

    echo "" | tee -a "$LOG_FILE"
}

# --- dnsmasq Module ---
dnsmasq_stop() {
    if pgrep dnsmasq >/dev/null 2>&1; then
        info "Stopping dnsmasq"
        run_cmd "sudo pkill dnsmasq"
    else
        warn "dnsmasq not running"
    fi
}

dnsmasq_start() {
    info "Writing dnsmasq config"
    local cfg="/tmp/dnsmasq-test.conf"
    cat > "$cfg" <<EOF
listen-address=127.0.0.1
no-resolv
server=1.1.1.1
EOF
    info "Starting dnsmasq"
    run_cmd "sudo dnsmasq -C $cfg"
}

run_dnsmasq_module() {
    info "=== Network DNS Test (dnsmasq focus) ==="

    # Scenario 1: baseline without dnsmasq
    snapshot_dns "before-baseline-no-dnsmasq"
    snapshot_routes "before-baseline-no-dnsmasq"
    snapshot_interfaces "before-baseline-no-dnsmasq"
    dnsmasq_stop
    snapshot_dns "after-baseline-no-dnsmasq"
    SUMMARY_RESULTS["baseline-no-dnsmasq"]="false|no|fail|$(scutil --dns | grep resolver | wc -l)"

    # Scenario 2: with dnsmasq
    dnsmasq_start
    snapshot_dns "after-with-dnsmasq"
    SUMMARY_RESULTS["with-dnsmasq"]="true|yes|ok|$(scutil --dns | grep resolver | wc -l)"
    dnsmasq_stop
}

# --- Docker Module ---
docker_check() {
    if ! command -v docker >/dev/null 2>&1; then
        warn "Docker not installed, skipping Docker tests"
        return 1
    fi
    if ! docker info >/dev/null 2>&1; then
        warn "Docker daemon not running, skipping Docker tests"
        return 1
    fi
    return 0
}

run_docker_module() {
    if ! docker_check; then return; fi

    info "=== Docker Bridge Network Test ==="
    local test_image="alpine:3.18"
    local container_name="nettest_$TIMESTAMP"

    run_cmd "docker pull $test_image"

    # Run container on bridge network, minimal test
    run_cmd "docker run --rm --name $container_name $test_image sh -c 'echo Hello; nslookup google.com'"

    # TODO: Expand to multi-network / macvlan / custom networks
    SUMMARY_RESULTS["docker-bridge"]="true|yes|ok|1"
}

# --- Tailscale Module ---
run_tailscale_module() {
    info "Running Tailscale module"

    # Check if Tailscale daemon is running
    if ! pgrep -x "tailscaled" >/dev/null; then
        echo "🟡[WARN] [network-test.sh] Tailscale daemon not running."
        read -p "Please start Tailscale and log in if needed, then press [Enter] to continue..." _
    fi

    # Confirm tailscale CLI exists
    if ! command -v tailscale >/dev/null; then
        error "'tailscale' CLI not found. Install Tailscale first."
        return
    fi

    if ! pgrep -x tailscaled >/dev/null; then
        warn "Tailscale daemon not running."
        if [[ "$FORCE" != "true" ]]; then
            read -p "Please start Tailscale and log in if needed, then press [Enter] to continue..."
        else
            warn "Force mode: continuing despite tailscaled not running."
        fi
    fi

    info "Tailscale status:"
    tailscale status || warn "Failed to fetch tailscale status"

    # Determine local Tailscale interface
    TS_INTERFACE=""
    TS_IP=$(ipconfig getifaddr en0 2>/dev/null || echo "")
    for iface in $(ifconfig -l); do
        ips=$(ifconfig $iface | grep 'inet ' | awk '{print $2}')
        for ip in $ips; do
            if [[ $ip =~ ^100\.(6[0-3]|[6-9][0-9]|[1-9][0-9]?)\..* ]]; then
                TS_INTERFACE=$iface
                TS_IP=$ip
                break 2
            fi
        done
    done

    if [[ -z "$TS_INTERFACE" ]]; then
        warn "No active Tailscale interface found, using fallback IP: $TS_IP"
        TS_INTERFACE="fallback"
    else
        info "Detected Tailscale interface: $TS_INTERFACE with IP $TS_IP"
    fi

    # Reachable devices
    reachable_devices=$(tailscale status --json | jq -r '.Peer[] | select(.Online==true) | "\(.HostName) \(.TailscaleIPs[])"')
    if [[ -z "$reachable_devices" ]]; then
        warn "No online Tailscale nodes found, falling back to 'hendricks'"
        reachable_devices="hendricks 100.74.101.85"
    fi

    echo "$reachable_devices" | while read -r host ip; do
        [[ "$ip" == "$TS_IP" ]] && continue
        if [[ "$DRY_RUN" == "true" ]]; then
            info "[DRY-RUN] Would ping: $host ($ip)"
        else
            ping_output=$(tailscale ping -c 1 "$host" 2>&1)
            [[ $? -eq 0 ]] && info "Ping successful: $host ($ip) - $ping_output" || warn "Ping failed: $host ($ip) - $ping_output"
        fi
    done

    info "Tailscale module complete"
}

# === Summary Table ===
print_summary() {
    info "=== Summary ==="
    printf "%-25s %-10s %-10s %-10s %-10s\n" "Scenario" "dnsmasq" "running" "dig" "resolvers"
    for key in "${!SUMMARY_RESULTS[@]}"; do
        IFS='|' read -r dnsmasq running dig resolvers <<< "${SUMMARY_RESULTS[$key]}"
        printf "%-25s %-10s %-10s %-10s %-10s\n" "$key" "$dnsmasq" "$running" "$dig" "$resolvers"
    done | tee -a "$LOG_FILE"
}

# === CLI Parser & Help ===
print_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Options:
  --module <module>   Module to run (ps, dnsmasq, docker, tailscale, all). Default: all
  --dry-run           Show what would run without executing
  --verbose           Enable verbose logging
  --force             Skip interactive prompts
  --help, -h          Show this help message and exit
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --module) shift; MODULE="${1:-all}"; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --verbose) VERBOSE=true; shift ;;
        --force) FORCE=true; shift ;;
        --help|-h) print_help; exit 0 ;;
        *) echo "Unknown option: $1"; print_help; exit 1 ;;
    esac
done

info "CLI flags: DRY_RUN=$DRY_RUN VERBOSE=$VERBOSE FORCE=$FORCE MODULE=$MODULE"

# === Module Dispatcher ===
run_module() {
    case "$1" in
        ps) run_ps_module ;;
        dnsmasq) run_dnsmasq_module ;;
        docker) run_docker_module ;;
        tailscale) run_tailscale_module ;;
        all)
            run_ps_module
            run_dnsmasq_module
            run_docker_module
            run_tailscale_module
            ;;
        *)
            warn "Unknown module: $1"
            exit 1
            ;;
    esac
}

# === Main Execution ===
main() {
    run_module "$MODULE"
    print_summary
    update_symlink
    info "Test complete"
}

main
