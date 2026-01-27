#!/usr/bin/env bash
# network-test.sh
# Modern Bash network tester (dnsmasq + Docker + Tailscale)
# JSON snapshot outputs, modular, verbose, dry-run, cross-platform aware

set -euo pipefail
IFS=$'\n\t'

# === Globals ===
SCRIPT_NAME=$(basename "$0")
BASEDIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# --- Logs ---
LOG_DIR="$BASEDIR/logs"
mkdir -p "$LOG_DIR"
TIMESTAMP=$(/bin/date +%Y%m%d-%H%M%S)
LOG_FILE="$LOG_DIR/network_test.$TIMESTAMP.log"
SYMLINK="$LOG_DIR/latest-net.log"

# Default flags
DRY_RUN=false
VERBOSE=false
FORCE=false
MODULE="all"

declare -A SUMMARY_RESULTS

# === Colors & Emojis ===
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

EMOJI_INFO="🟢"
EMOJI_WARN="🟡"
EMOJI_ERROR="🔴"
EMOJI_OK="✅"

# Silence unused SC2034 warnings
: "$RED" "$GREEN" "$YELLOW" "$BLUE" "$NC" "$EMOJI_OK"

# === Command wrappers (updated later, in preflight) ===
cmd_sed="/usr/bin/sed"
cmd_awk="/usr/bin/awk"
cmd_date="/bin/date"   # fallback for early logging
cmd_jq=""
cmd_ip2mac=""
cmd_ps="/bin/ps"

# === Preflight: detect/install tools ===
detect_and_install_tools() {
    info "🟢 Checking GNU utilities prerequisites..."

    # Map of commands → wrappers
    local -A gnutils=( ["gsed"]="sed" ["gawk"]="awk" ["gdate"]="date" ["jq"]="jq" ["iproute2mac"]="ip2mac" ["ps"]="ps" )

    local cmd bin
    for cmd in "${!gnutils[@]}"; do
        if bin=$(command -v "$cmd" 2>/dev/null); then
            info "Found $cmd → $bin"
            declare -g "cmd_${gnutils[$cmd]}=$bin"
        else
            warn "$cmd not found"
        fi
    done

    info "✅ GNU utility preflight complete."
}

# === Logging Helpers ===
log() {
    local level="$1"; shift
    local msg="$*"
    echo -e "${level} [${SCRIPT_NAME}] $($cmd_date '+%T') $msg" | tee -a "$LOG_FILE"
}
info()  { log "${EMOJI_INFO}[INFO]" "$@"; }
warn()  { log "${EMOJI_WARN}[WARN]" "$@"; }
error() { log "${EMOJI_ERROR}[ERROR]" "$@"; }

run_cmd() {
    local cmd="$*"
    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] $cmd"
    else
        eval "$cmd"
    fi
}

# === Symlink latest log ===
update_symlink() {
    ln -sf "$LOG_FILE" "$SYMLINK"
    info "Updated symlink: $SYMLINK -> $LOG_FILE"
}

# === JSON Snapshots ===
snapshot_dns() {
    local label="$1"
    info "🟢 Snapshot DNS ($label)"

    local resolv_json
    resolv_json=$($cmd_jq -n --rawfile r /etc/resolv.conf "\$r | split(\"\n\")")
    echo "{\"label\":\"$label\",\"resolv_conf\":$resolv_json}" >> "$LOG_FILE"

    if scutil --dns >/dev/null 2>&1; then
        local scutil_json
        scutil_json=$(scutil --dns | $cmd_jq -R -s 'split("\n")')
        echo "{\"label\":\"$label\",\"scutil_dns\":$scutil_json}" >> "$LOG_FILE"
    else
        warn "scutil --dns failed"
    fi
}

snapshot_routes() {
    local label="$1"
    info "🟢 Snapshot routes ($label)"

    if command -v netstat >/dev/null 2>&1; then
        local routes_json
        routes_json=$(netstat -rn | $cmd_jq -R -s 'split("\n")')
        echo "{\"label\":\"$label\",\"routes\":$routes_json}" >> "$LOG_FILE"
    else
        warn "netstat not available"
    fi
}

snapshot_interfaces() {
    local label="$1"
    info "🟢 Snapshot interfaces ($label)"

    if command -v ifconfig >/dev/null 2>&1; then
        local if_json
        if_json=$(ifconfig | $cmd_jq -R -s 'split("\n")')
        echo "{\"label\":\"$label\",\"interfaces\":$if_json}" >> "$LOG_FILE"
    else
        warn "ifconfig not available"
    fi
}

# === Modules ===

# --- PS Module ---
run_ps_module() {
    info "🟢 Starting process snapshot module"
    [[ "$VERBOSE" == true ]] && info "Listing all relevant processes..."

    if [[ -n "$cmd_ps" && -n "$cmd_jq" ]]; then
        # JSON array of PS output lines, non-interactive
        ps_json=$($cmd_ps -e -o pid,comm | $cmd_jq -R -s 'split("\n")')
        echo "{\"module\":\"ps\",\"processes\":$ps_json}" >> "$LOG_FILE"
    else
        warn "cmd_ps or cmd_jq not defined"
    fi

    info "✅ Process snapshot complete"
    echo
}

# --- DNSMasq Module ---
dnsmasq_stop() {
    info "🟡 Stopping dnsmasq if running"
    if pgrep dnsmasq >/dev/null 2>&1; then
        run_cmd "sudo pkill dnsmasq"
        info "✅ dnsmasq stopped"
    else
        warn "dnsmasq not running"
    fi
}

dnsmasq_start() {
    info "🟢 Writing dnsmasq test config"
    local cfg="/tmp/dnsmasq-test.conf"

    cat > "$cfg" <<EOF
listen-address=127.0.0.1
no-resolv
server=1.1.1.1
EOF

    info "🟢 Starting dnsmasq daemon"
    run_cmd "sudo dnsmasq -C $cfg"
}

run_dnsmasq_module() {
    info "🟢 Running DNSMasq module"
    snapshot_dns "before-dnsmasq"
    dnsmasq_stop
    snapshot_dns "after-stop"
    dnsmasq_start
    snapshot_dns "after-start"
    dnsmasq_stop
    info "✅ DNSMasq module complete"
    echo
}

# --- Docker Module ---
docker_check() {
    if ! command -v docker >/dev/null 2>&1; then
        warn "Docker CLI not installed, skipping Docker module"
        return 1
    fi
    if ! docker info >/dev/null 2>&1; then
        warn "Docker daemon not running, skipping Docker module"
        return 1
    fi
    return 0
}

run_docker_module() {
    info "🟢 Running Docker network module"

    if ! docker_check; then
        warn "Docker module skipped"
        return
    fi

    local test_image="alpine:3.18"
    local timestamp
    timestamp=$($cmd_date '+%s')
    local container_name="nettest_$timestamp"

    run_cmd "docker pull $test_image"
    run_cmd "docker run --rm --name $container_name $test_image sh -c 'echo Hello; nslookup google.com'"

    info "✅ Docker network module complete"
    echo
}

# --- Tailscale Module ---
run_tailscale_module() {
    info "🟢 Starting Tailscale module"

    local TS_GUI_PID TS_DAEMON_PID TS_BIN TS_INTERFACE TS_IP reachable_devices TS_STATUS
    TS_GUI_PID=$(pgrep -f 'Tailscale')
    TS_DAEMON_PID=$(pgrep -f 'tailscaled')

    [[ -n "$TS_GUI_PID" ]] && info "Tailscale GUI detected (PID $TS_GUI_PID)"

    if [[ -z "$TS_DAEMON_PID" ]]; then
        for candidate in "$(command -v tailscaled 2>/dev/null)" "$HOME/go/bin/tailscaled"; do
            [[ -x "$candidate" ]] && TS_BIN="$candidate" && break
        done
        [[ -n "$TS_BIN" ]] && run_cmd "sudo $TS_BIN &" && sleep 2 && TS_DAEMON_PID=$(pgrep -f 'tailscaled')
    fi

    if [[ -z "$TS_GUI_PID" && -z "$TS_DAEMON_PID" ]]; then
        [[ "$FORCE" != true ]] && read -r -p "Start Tailscale manually, then press [Enter]..."
        warn "No Tailscale processes detected"
        return
    fi

    TS_VERSION=$(tailscale version 2>/dev/null || echo "unknown")
    info "Tailscale version: $TS_VERSION"

    TS_STATUS=$(tailscaled status --json 2>/dev/null || tailscale status || echo "{}")
    info "Tailscale status:\n$TS_STATUS"

    TS_INTERFACE=""
    TS_IP=""
    for iface in $($cmd_ip2mac -l); do
        ips=$($cmd_ip2mac "$iface" | $cmd_awk '/inet /{print $2}')
        for ip in $ips; do
            [[ $ip =~ ^100\..* ]] && TS_INTERFACE=$iface && TS_IP=$ip && break 2
        done
    done
    TS_INTERFACE=${TS_INTERFACE:-fallback}
    TS_IP=${TS_IP:-""}
    info "Detected Tailscale interface: $TS_INTERFACE, IP: $TS_IP"

    reachable_devices=$(tailscale status --json 2>/dev/null | $cmd_jq -r '.Peer[] | select(.Online==true) | "\(.HostName) \(.TailscaleIPs[])"')
    reachable_devices=${reachable_devices:-"hendricks 100.74.101.85"}

    while read -r host ip; do
        [[ "$ip" == "$TS_IP" ]] && continue
        if [[ "$DRY_RUN" == true ]]; then
            info "[DRY-RUN] Would ping: $host ($ip)"
        else
            if tailscale ping -c 1 "$host" >/dev/null 2>&1; then
                info "Ping successful: $host ($ip)"
            else
                warn "Ping failed: $host ($ip)"
            fi
        fi
    done <<< "$reachable_devices"

    info "✅ Tailscale module complete"
    echo
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
    detect_and_install_tools
    run_module "$MODULE"
    print_summary
    update_symlink
    info "Test complete"
}

main
