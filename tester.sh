#!/usr/bin/env bash
set -exuo pipefail

# ========================================
# Docker + Tailscale + NordVPN DNS Test
# ========================================

LOG_FILE="./dns_test.${RANDOM}.log"
DOCKER_CONTAINER="$(diceware -n 2 -d- | tr '[:upper:]' '[:lower:]')"
DOCKER_IMAGE="nginx"
LOOPBACK_IP="10.0.0.1"
BREW_PREFIX="$(brew --prefix)"
DNSMASQ_CONF="$BREW_PREFIX/etc/dnsmasq.d/docker-hosts.conf"

RED="\033[0;31m"
GREEN="\033[0;32m"
RESET="\033[0m"
BELL="\a"

# -------------------------------
# Helpers
# -------------------------------

log() {
    echo -e "${GREEN}[INFO] $*${RESET}" | tee -a "$LOG_FILE"
}

warn() {
    echo -e "${RED}[WARN] $*${RESET}${BELL}" | tee -a "$LOG_FILE"
}

confirm() {
    local msg="$1"
    read -rp "$msg [y/N] " resp
    [[ "$resp" =~ ^[Yy]$ ]]
}

check_service() {
    local svc=$1
    if pgrep -x "$svc" >/dev/null; then
        log "$svc is running."
        if confirm "Stop $svc?"; then
            sudo pkill -9 "$svc" || true
            log "$svc stopped."
        fi
    else
        log "$svc not running."
    fi
}

ensure_dnsmasq_zone() {
    local ip docker_ip
    docker_ip=$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$DOCKER_CONTAINER" 2>/dev/null || echo "$LOOPBACK_IP")
    if [[ ! -s "$DNSMASQ_CONF" ]]; then
        log "Populating dnsmasq zone file..."
        cat >"$DNSMASQ_CONF" <<EOF
address=/$DOCKER_CONTAINER.internal/$docker_ip
EOF
        log "dnsmasq zone file configured for $DOCKER_CONTAINER.internal -> $docker_ip"
    fi
}

start_dnsmasq() {
    ensure_dnsmasq_zone
    if pgrep -x "dnsmasq" >/dev/null; then
        log "Stopping existing dnsmasq..."
        sudo pkill -9 dnsmasq || true
    fi
    log "Starting dnsmasq..."
    sudo "$BREW_PREFIX"/opt/dnsmasq/sbin/dnsmasq \
        --keep-in-foreground --listen-address="$LOOPBACK_IP" \
        --conf-file="$DNSMASQ_CONF" --no-resolv --bind-interfaces &
    sleep 1
    if pgrep -x "dnsmasq" >/dev/null; then
        log "dnsmasq is running."
    else
        warn "dnsmasq failed to start!"
    fi
}

show_dns() {
    log "--- /etc/resolv.conf ---"
    cat /etc/resolv.conf | tee -a "$LOG_FILE"
    log "--- scutil --dns ---"
    scutil --dns | tee -a "$LOG_FILE"
}

docker_run_test_container() {
    if docker ps --format '{{.Names}}' | grep -q "^$DOCKER_CONTAINER\$"; then
        docker rm -f "$DOCKER_CONTAINER" || true
    fi
    log "Starting test container $DOCKER_CONTAINER..."
    docker run -d --name "$DOCKER_CONTAINER" "$DOCKER_IMAGE"
}

tailscale_action() {
    local action=$1
    if [[ "$action" == "start" ]]; then
        log "Starting Tailscale..."
        sudo tailscale up --accept-routes --accept-dns || warn "Tailscale up failed"
    elif [[ "$action" == "stop" ]]; then
        sudo pkill -9 tailscaled || log "Tailscale not running"
        log "Tailscale stopped."
    fi
}

nordvpn_app_running() {
    pgrep -fx "/Applications/NordVPN.app/Contents/MacOS/NordVPN" >/dev/null
}

nordvpn_action() {
    local action=$1

    if [[ "$action" == "start" ]]; then
        if nordvpn_app_running; then
            log "NordVPN.app already running."
        else
            log "Starting NordVPN.app..."
            open -a NordVPN
            read -rp "Press Enter after NordVPN.app has fully started..."
        fi
    elif [[ "$action" == "stop" ]]; then
        if nordvpn_app_running; then
            warn "Please manually quit NordVPN.app to continue."
            read -rp "Press Enter after NordVPN.app has been closed..."
            log "Confirmed NordVPN.app closed."
        else
            log "NordVPN.app not running."
        fi
    fi
}

capture_routes() {
    netstat -rn -f inet >"$1"
}

diff_routes() {
    diff -u "$1" "$2" | tee -a "$LOG_FILE"
}

run_scenario() {
    local scenario=$1
    local ts_action=$2
    local vpn_action=$3
    local ROUTES_BEFORE ROUTES_AFTER

    echo | tee -a "$LOG_FILE"
    log "=== Scenario: $scenario ==="
    show_dns

    capture_routes "/tmp/routes_before_${scenario// /_}.txt"

    tailscale_action "$ts_action"
    nordvpn_action "$vpn_action"

    start_dnsmasq

    capture_routes "/tmp/routes_after_${scenario// /_}.txt"
    diff_routes "/tmp/routes_before_${scenario// /_}.txt" "/tmp/routes_after_${scenario// /_}.txt"

    # Docker hostname resolution
    echo "--- Docker ---" | tee -a "$LOG_FILE"
    if ! ping -c 2 "$DOCKER_CONTAINER.internal" 2>&1 | tee -a "$LOG_FILE"; then
        warn "Ping failed!"
    fi
    if ! dig A "$DOCKER_CONTAINER.internal" +short 2>&1 | tee -a "$LOG_FILE"; then
        warn "dig failed!"
    fi

    # Tailscale resolution
    echo "--- Tailscale ---" | tee -a "$LOG_FILE"
    TS_HOST=$(tailscale status --json | jq -r '.Peer[]?.HostName' 2>/dev/null | grep -v "^$(hostname)$" | shuf -n1 || true)
    if [[ -n "$TS_HOST" ]]; then
        if ! ping -c 2 "$TS_HOST" 2>&1 | tee -a "$LOG_FILE"; then
            warn "Ping failed!"
        fi
        if ! tailscale ping "$TS_HOST" 2>&1 | tee -a "$LOG_FILE"; then
            warn "tailscale ping failed!"
        fi
        if ! dig A "$TS_HOST" +short 2>&1 | tee -a "$LOG_FILE"; then
            warn "dig failed!"
        fi
    else
        log "No remote Tailscale host found, skipping ping/dig."
    fi
}

# -------------------------------
# Main Flow
# -------------------------------

log "=== Docker + Tailscale + VPN DNS Test ==="
log "Stopping all services if running..."
check_service docker
check_service tailscaled
check_service dnsmasq

if ! nordvpn_app_running; then
    log "Please exit NordVPN manually if needed."
fi

docker_run_test_container

# Run scenarios
run_scenario "Neither running" stop stop
run_scenario "NordVPN only" stop start
run_scenario "Tailscale only" start stop
run_scenario "Both running" start start

# Cleanup
log "Stopping test container..."
docker rm -f "$DOCKER_CONTAINER" || true
tailscale_action stop
nordvpn_action stop
log "Stopping dnsmasq..."
sudo pkill -9 dnsmasq || true

log "All scenarios complete. Log file: $LOG_FILE"
log "Review results and follow any WARN messages."
