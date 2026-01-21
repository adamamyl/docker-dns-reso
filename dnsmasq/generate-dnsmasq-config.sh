#!/usr/bin/env bash
set -euo pipefail

OS="$(uname)"

# macOS setup
if [[ "$OS" == "Darwin" ]]; then
    # Brew
    PREFIX="$(brew --prefix)"
    CONF="$PREFIX/etc/dnsmasq.conf"
    DIR="$PREFIX/etc/dnsmasq.d"

    # Ensure dnsmasq.d directory exists
    mkdir -p "$DIR"
    
    # Create empty Docker hosts config (will be updated dynamically)
    install -m 644 /dev/null "$DIR/docker-hosts.conf"

    # Include help.internal TXT record
    install -m 644 ../dnsmasq/help-internal.conf "$DIR/help-internal.conf"

    # Main dnsmasq.conf
    cat >"$CONF" <<EOF
# Listen only on localhost
listen-address=127.0.0.1
listen-address=::1
bind-interfaces
# Include dynamic Docker hosts
conf-file=$DIR/docker-hosts.conf
# Include static help TXT record
conf-file=$DIR/help-internal.conf
EOF

    # Done for macOS
    exit 0
fi

# Linux setup
PORT_FILE="/etc/dnsmasq.d/docker.port"
CONF="/etc/dnsmasq.d/docker.conf"

# Select a random high port for Docker DNS
if [[ -f "$PORT_FILE" ]]; then
  # Reuse previously assigned port
  PORT="$( < "$PORT_FILE")"
else
  # Pick a random port between 50000-59999 that's not in use
  while :; do
    PORT=$((RANDOM % 10000 + 50000))
    # Check if port is already listening
    ss -ltn | awk '{print $4}' | grep -q ":$PORT$" || break
  done
  # Save port for future runs
  echo "$PORT" | sudo tee "$PORT_FILE" >/dev/null
  sudo chmod 644 "$PORT_FILE"
fi

# Create empty Docker hosts config
sudo install -m 644 /dev/null /etc/dnsmasq.d/docker-hosts.conf

# Include help.internal TXT record
sudo install -m 644 ../dnsmasq/help-internal.conf /etc/dnsmasq.d/help-internal.conf

# Main dnsmasq configuration
sudo tee "$CONF" >/dev/null <<EOF
# Listen on localhost
port=$PORT
listen-address=127.0.0.1
listen-address=::1
bind-interfaces
# Include dynamic Docker hosts
conf-file=/etc/dnsmasq.d/docker-hosts.conf
# Include static help TXT record
conf-file=/etc/dnsmasq.d/help-internal.conf
EOF


# Pull system/DHCP DNS servers as fallback
SYSTEM_DNS=""
if command -v resolvectl >/dev/null 2>&1; then
    SYSTEM_DNS=$(resolvectl status | grep 'DNS Servers' | awk '{print $3}')
else
    SYSTEM_DNS=$(grep '^nameserver' /etc/resolv.conf | awk '{print $2}')
fi

for s in $SYSTEM_DNS; do
    echo "server=$s" | sudo tee -a "$CONF" >/dev/null
done


# Configure systemd-resolved split DNS
sudo mkdir -p /etc/systemd/resolved.conf.d
sudo tee /etc/systemd/resolved.conf.d/docker.conf >/dev/null <<EOF
[Resolve]
# Use local dnsmasq for *.internal domains
DNS=127.0.0.1#$PORT
Domains=~internal
EOF

# Restart services
sudo systemctl restart systemd-resolved
sudo systemctl restart dnsmasq
