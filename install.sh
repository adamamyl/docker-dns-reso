#!/usr/bin/env bash
set -euo pipefail

OS="$(uname)"

echo "Installing docker-dns on $OS"

if [[ "$OS" == "Darwin" ]]; then
    brew install dnsmasq jq || true
    brew services start dnsmasq

    PREFIX="$(brew --prefix)"
    mkdir -p "$PREFIX/etc/dnsmasq.d"
else
    sudo apt update
    sudo apt install -y dnsmasq jq
    sudo systemctl enable --now dnsmasq

    sudo mkdir -p /etc/dnsmasq.d
    # MUST exist or dnsmasq refuses to start
    sudo install -m 644 /dev/null /etc/dnsmasq.d/docker-hosts.conf
fi

# Generate dnsmasq + resolver config
./dnsmasq/generate-dnsmasq-config.sh

# Install updater
sudo install -m 755 docker-dns-updater.sh /usr/local/bin/docker-dns-updater.sh

if [[ "$OS" == "Darwin" ]]; then
    sudo mkdir -p /etc/resolver
    sudo install -m 644 macos/resolver/internal /etc/resolver/internal

    sudo install -m 644 macos/docker-dns-updater.plist \
        /Library/LaunchDaemons/com.docker.dnsupdater.plist
    sudo launchctl load -w \
        /Library/LaunchDaemons/com.docker.dnsupdater.plist
else
    sudo install -m 644 systemd/docker-dns-updater.service /etc/systemd/system/
    sudo install -m 644 systemd/docker-dns-updater.timer /etc/systemd/system/

    sudo systemctl daemon-reexec
    sudo systemctl enable --now docker-dns-updater.timer
fi

# Initial run
sudo /usr/local/bin/docker-dns-updater.sh || true

echo "docker-dns installed"
