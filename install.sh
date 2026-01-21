#!/usr/bin/env bash
set -euo pipefail
# ------------------------------------------------------------------
# Installer for docker-dns + optional Quad9 and plain DNS setup
# Supports:
#   - Docker dynamic DNS (*.internal)
#   - Quad9 DNS over TLS (macOS only)
#   - Plain DNS (fallback / default resolver)
# ------------------------------------------------------------------

OS="$(uname)"
CONFIG="all"       # default install: docker + quad9 + plain
UPDATE_PROFILE=0

# Parse options
while [[ $# -gt 0 ]]; do
    case "$1" in
        --config=*)
            CONFIG="${1#*=}"
            ;;
        --update-profile)
            UPDATE_PROFILE=1
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
    shift
done

echo "Installing docker-dns on $OS (config=$CONFIG)..."

# Install dep(endencie)s
DEPS=(dnsmasq jq)

if [[ "$OS" == "Darwin" ]]; then
    for p in "${DEPS[@]}"; do
        if ! command -v "$p" >/dev/null 2>&1; then
            echo "Installing $p..."
            brew install "$p"
        fi
    done

    # Start dnsmasq if not running
    if ! brew services list | grep -q '^dnsmasq.*started'; then
        brew services start dnsmasq
    fi

    PREFIX="$(brew --prefix)"
    mkdir -p "$PREFIX/etc/dnsmasq.d"
else
    # Linux (Debian/Ubuntu) installation
    APT_UPDATED=0
    for p in "${DEPS[@]}"; do
        if ! command -v "$p" >/dev/null 2>&1; then
            if [[ $APT_UPDATED -eq 0 ]]; then
                echo "Running apt update..."
                sudo apt update
                APT_UPDATED=1
            fi
            echo "Installing $p..."
            sudo apt install -y "$p"
        fi
    done

    # Enable and start dnsmasq service if not active
    if ! systemctl is-active --quiet dnsmasq; then
        sudo systemctl enable --now dnsmasq
    fi

    mkdir -p /etc/dnsmasq.d
fi

# Ensure docker-hosts.conf exists
if [[ "$OS" == "Darwin" ]]; then
    install -m 644 /dev/null "$PREFIX/etc/dnsmasq.d/docker-hosts.conf"
else
    sudo install -m 644 /dev/null /etc/dnsmasq.d/docker-hosts.conf
fi

# Generate dnsmasq configuration (Docker)
if [[ "$CONFIG" == "docker" ]] || [[ "$CONFIG" == "all" ]]; then
    ./dnsmasq/generate-dnsmasq-config.sh
fi

# Install updater script
sudo install -m 755 docker-dns-updater.sh /usr/local/bin/docker-dns-updater.sh

# Resolver / LaunchDaemon / systemd setup
if [[ "$OS" == "Darwin" ]]; then
    # macOS resolver for *.internal
    sudo mkdir -p /etc/resolver
    sudo install -m 644 macos/resolver/internal /etc/resolver/internal

    # Install LaunchDaemon
    PLIST_SRC="macos/docker-dns-updater.plist"
    PLIST_DST="/Library/LaunchDaemons/com.docker.dnsupdater.plist"
    sudo install -m 644 "$PLIST_SRC" "$PLIST_DST"

    # Reload daemon
    sudo launchctl unload -w "$PLIST_DST" 2>/dev/null || true
    sudo launchctl load -w "$PLIST_DST"

    # Apply Quad9 profile if requested
    if [[ "$CONFIG" == "quad9" ]] || [[ "$CONFIG" == "all" ]] || [[ $UPDATE_PROFILE -eq 1 ]]; then
        sudo /usr/local/bin/docker-dns-updater.sh --update-profile
    fi
else
    # Linux systemd setup
    sudo install -m 644 systemd/docker-dns-updater.service /etc/systemd/system/
    sudo install -m 644 systemd/docker-dns-updater.timer /etc/systemd/system/

    sudo systemctl daemon-reexec
    sudo systemctl enable --now docker-dns-updater.timer

    if [[ "$CONFIG" == "quad9" ]] || [[ "$CONFIG" == "all" ]]; then
        echo "Quad9 mobileconfig profile not supported on Linux. Configure manually if desired."
    fi
fi

# Initial DNS updater
if [[ "$CONFIG" == "docker" ]] || [[ "$CONFIG" == "all" ]]; then
    sudo /usr/local/bin/docker-dns-updater.sh --force
fi

echo "docker-dns installation complete."
