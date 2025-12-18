# docker-dns

Local Docker DNS for development using dnsmasq.

## Features
- `*.internal` domain
- IPv4 + IPv6
- Multiple Docker networks
- Collision-safe hostnames
- systemd-resolved split DNS (Linux)
- macOS resolver support
- Safe with Tailscale
- Automatic refresh every 10 minutes
- Manual refresh supported

## Install
```bash
./install.sh
```

## Usage
### Manual refresh:
```bash
docker-dns-updater.sh
```
### Test hostname:
```bash
docker run -d --name web nginx
ping web.internal
```

## Flags
for docker-dns-updater.sh:

 - --debug
 - --quiet
 - --dry-run
 - --force

## Make scripts executable
Either 
```bash
find . -type f -name '*.sh' -exec chmod a+x {} +
```

or 

```bash
shopt -s globstar
chmod a+x **/*.sh```
```