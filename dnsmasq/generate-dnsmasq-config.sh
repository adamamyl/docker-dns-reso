#!/usr/bin/env bash
set -euo pipefail

OS="$(uname)"

# macOS
if [[ "$OS" == "Darwin" ]]; then
    PREFIX="$(brew --prefix)"
    CONF="$PREFIX/etc/dnsmasq.conf"
    DIR="$PREFIX/etc/dnsmasq.d"

    mkdir -p "$DIR"
    install -m 644 /dev/null "$DIR/docker-hosts.conf"

    cat >"$CONF" <<EOF
listen-address=127.0.0.1
listen-address=::1
bind-interfaces
conf-file=$DIR/docker-hosts.conf
EOF
    exit 0
fi

# Linux
PORT_FILE="/etc/dnsmasq.d/docker.port"
CONF="/etc/dnsmasq.d/docker.conf"

if [[ -f "$PORT_FILE" ]]; then
    PORT="$(cat "$PORT_FILE")"
else
    while :; do
        PORT=$((RANDOM % 10000 + 50000))
        ss -ltn | awk '{print $4}' | grep -q ":$PORT$" || break
    done
    echo "$PORT" | sudo tee "$PORT_FILE" >/dev/null
    sudo chmod 644 "$PORT_FILE"
fi

sudo install -m 644 /dev/null /etc/dnsmasq.d/docker-hosts.conf

sudo tee "$CONF" >/dev/null <<EOF
port=$PORT
listen-address=127.0.0.1
listen-address=::1
bind-interfaces
conf-file=/etc/dnsmasq.d/docker-hosts.conf
EOF

sudo mkdir -p /etc/systemd/resolved.conf.d
sudo tee /etc/systemd/resolved.conf.d/docker.conf >/dev/null <<EOF
[Resolve]
DNS=127.0.0.1#$PORT
Domains=~internal
EOF

sudo systemctl restart systemd-resolved
sudo systemctl restart dnsmasq
