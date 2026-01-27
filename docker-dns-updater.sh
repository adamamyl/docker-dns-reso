#!/usr/bin/env bash
# ------------------------------------------------------------------
# - Updates dnsmasq with Docker container hostnames (IPv4 + IPv6)
# - Adds a self-documenting TXT record (help.internal)
# - On macOS, can optionally apply the Quad9 mobileconfig profile
# ------------------------------------------------------------------

set -euo pipefail

# Flags
DEBUG=0
DRY_RUN=0
FORCE=0
QUIET=0
UPDATE_PROFILE=0
USE_SYSTEM_DNS=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --debug)            DEBUG=1     ;;
        --dry-run)          DRY_RUN=1   ;;
        --force)            FORCE=1     ;;
        --quiet)            QUIET=1     ;;
        --update-profile)   UPDATE_PROFILE=1    ;;
        --use-system-dns)   USE_SYSTEM_DNS=1    ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
    shift
done

if [[ $DEBUG -eq 1 ]]; then
    set -x
fi

# OS detection
OS="$(uname)"

# dnsmasq configuration path
DNS_FILE="/etc/dnsmasq.d/docker-hosts.conf"
if [[ "$OS" == "Darwin" ]]; then
    DNS_FILE="$(brew --prefix)/etc/dnsmasq.d/docker-hosts.conf"
fi


# Temp file
TMP="$(mktemp)"
declare -A SEEN

# Logging
log() {
    if [[ $QUIET -eq 0 ]]; then
        echo "$@"
    fi
}

# macOS Quad9 profile
QUAD9_URL="https://docs.quad9.net/assets/mobileconfig/Quad9_Secured_DNS_over_TLS_20260119.mobileconfig"

apply_quad9_profile() {
    # Only macOS supports the profile
    if [[ "$OS" == "Darwin" ]]; then
        log "Applying Quad9 mobileconfig profile via Safari..."
        open -a Safari "$QUAD9_URL"
    else
        log "Quad9 mobileconfig profile is only supported on macOS. Skipping."
    fi
}

if [[ $UPDATE_PROFILE -eq 1 ]]; then
    apply_quad9_profile
fi

# Dockers
# Get all running container IDs
CONTAINERS="$(docker ps -q || true)"

# Exit early if no containers are running
if [[ -z "$CONTAINERS" ]]; then
    log "No running Docker containers detected."
    exit 0
fi

for ID in $CONTAINERS; do
    JSON="$(docker inspect "$ID")"
    # Extract container's name (remove leading '/')
    NAME="$(jq -r '.[0].Name | ltrimstr("/")' <<<"$JSON")"
    # Get networks container is connected to
    NETS="$(jq -r '.[0].NetworkSettings.Networks | keys[]' <<<"$JSON")"
    # Loop over all networks for container
    for NET in $NETS; do
        # Get container's IPv4 address
        IP4="$(jq -r --arg n "$NET" '
            try .[0].NetworkSettings.Networks[$n].IPAddress // empty
        ' <<<"$JSON")"
        # Get the container's IPv6 address
        IP6="$(jq -r --arg n "$NET" '
            try .[0].NetworkSettings.Networks[$n].GlobalIPv6Address // empty
        ' <<<"$JSON")"
        # Determine container's hostname
        # Default: containername.internal
        HOST="$NAME.internal"
        # If we've already seen a container with this name, add network as suffix
        # to avoid collisions (if multiple networks have same container name)
        if [[ -n "${SEEN[$NAME]+x}" ]]; then
            HOST="$NAME.$NET.internal"
        fi
        # Mark this container name as seen
        SEEN["$NAME"]=1
        # Append IP addresses to temporary dnsmasq file
        if [[ -n "$IP4" ]]; then
            echo "address=/$HOST/$IP4" >>"$TMP"
        fi
        if [[ -n "$IP6" ]]; then
            echo "address=/$HOST/$IP6" >>"$TMP"
        fi
    done
done

# Self-documenting TXT record
echo 'txt=help.internal,"https://github.com/adamamyl/docker-dns-reso/blob/main/README.md"' >>"$TMP"

# Inject system/DHCP DNS fallback (just in case…)
if [[ $USE_SYSTEM_DNS -eq 1 ]]; then
    log "Adding system/DHCP DNS servers as fallback..."
    if [[ "$OS" == "Darwin" ]]; then
        SYSTEM_DNS=$(scutil --dns | grep 'nameserver\[[0-9]*\]' | awk '{print $3}')
    else
        # Try systemd-resolved first
        if command -v resolvectl >/dev/null 2>&1; then
            SYSTEM_DNS=$(resolvectl status | grep 'DNS Servers' | awk '{print $3}')
        else
            SYSTEM_DNS=$(grep '^nameserver' /etc/resolv.conf | awk '{print $2}')
        fi
    fi

    for s in $SYSTEM_DNS; do
        echo "server=$s" >>"$TMP"
    done
fi

# Dry-run
if [[ $DRY_RUN -eq 1 ]]; then
    cat "$TMP"
    rm "$TMP"
    exit 0
fi

# Update dnsmasq configuration and reload dnsmasq
if [[ ! -f "$DNS_FILE" ]] || [[ $FORCE -eq 1 ]] || ! cmp -s "$TMP" "$DNS_FILE"; then
    sudo install -m 644 "$TMP" "$DNS_FILE"
    log "Reloading dnsmasq..."

    if [[ "$OS" == "Darwin" ]]; then
        brew services restart dnsmasq
    else
        sudo systemctl reload dnsmasq
    fi
fi

# Tidy-up
rm -f "$TMP"
log "Docker DNS updated successfully."
