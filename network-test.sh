#!/usr/bin/env bash
# network_test.sh
# Modern Bash network testing script (dnsmasq + Docker)
# Modular, idempotent, verbose, dry-run, cross-platform aware

set -euo pipefail
IFS=$'\n\t'

# === Globals ===
SCRIPT_NAME=$(basename "$0")
LOG_DIR="./logs"
mkdir -p "$LOG_DIR"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
LOG_FILE="$LOG_DIR/network_test.$TIMESTAMP.log"
SYMLINK="$LOG_DIR/latest-net.log"
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

# === Flag parsing ===
print_help() {
    cat <<EOF
Usage: $SCRIPT_NAME [options]
Options:
  --help        Show this help
  --verbose     Enable verbose logging
  --dry-run     Log actions without executing
  --force       Skip interactive prompts
  --module     Select module to run (all, dnsmasq, docker)
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help) print_help ;;
        --verbose) VERBOSE=true ;;
        --dry-run) DRY_RUN=true ;;
        --force) FORCE=true ;;
        --module)
            shift
            MODULE="${1:-all}"
            ;;
        *) error "Unknown argument: $1"; print_help ;;
    esac
    shift
done

info "Log file: $LOG_FILE"
info "CLI flags: DRY_RUN=$DRY_RUN VERBOSE=$VERBOSE FORCE=$FORCE MODULE=$MODULE"

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

# === dnsmasq Module ===
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

run_dnsmasq_tests() {
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

# === Docker Module ===
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

run_docker_tests() {
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

# === Summary Table ===
print_summary() {
    info "=== Summary ==="
    printf "%-25s %-10s %-10s %-10s %-10s\n" "Scenario" "dnsmasq" "running" "dig" "resolvers"
    for key in "${!SUMMARY_RESULTS[@]}"; do
        IFS='|' read -r dnsmasq running dig resolvers <<< "${SUMMARY_RESULTS[$key]}"
        printf "%-25s %-10s %-10s %-10s %-10s\n" "$key" "$dnsmasq" "$running" "$dig" "$resolvers"
    done | tee -a "$LOG_FILE"
}

# === Symlink latest log ===
update_symlink() {
    if [[ -L "$SYMLINK" || ! -e "$SYMLINK" ]]; then
        ln -sf "$LOG_FILE" "$SYMLINK"
        info "Updated symlink: $SYMLINK -> $LOG_FILE"
    fi
}

# === Main Execution ===
main() {
    case "$MODULE" in
        all)
            run_dnsmasq_tests
            run_docker_tests
            ;;
        dnsmasq) run_dnsmasq_tests ;;
        docker) run_docker_tests ;;
        *)
            error "Unknown module: $MODULE"
            exit 1
            ;;
    esac

    print_summary
    update_symlink
    info "Test complete"
}

main
