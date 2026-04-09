# docker-dns

Local Docker, Tailscale, VPN DNS routing using dnsmasq & profiles.

## Features

- `*.internal` domain
- IPv4 + IPv6 support
- Multiple Docker networks
- Collision-safe hostnames
- systemd-resolved split DNS (Linux)
- macOS resolver support
- Safe with Tailscale and NordVPN
- Automatic refresh every 10 minutes
- Manual refresh supported
- Self-documenting TXT record: `help.internal` points to [README](https://github.com/adamamyl/docker-dns-reso/blob/main/README.md)
- Supports Quad9 DNS over TLS and fallback DNS providers (Cloudflare Families)

## Install

```bash
sudo su
python3 install.py
```

## Use

### Manual refresh

```bash
docker-dns-updater.py
```

### Test hostname

```bash
docker run -d --name web nginx
ping web.internal
```

### TXT record

```bash
dig txt help.internal
```

Returns:

```text
" https://github.com/adamamyl/docker-dns-reso/blob/main/README.md "
```

## Flags for `docker-dns-updater.py`

- `--debug`            Enable bash tracing for troubleshooting
- `--quiet`            Suppress normal output
- `--dry-run`          Show the DNS configuration that would be applied, without writing
- `--force`            Force update even if config hasn't changed
- `--update-profile`   Re-download and apply latest Quad9 mobileconfig profile (macOS only)
- `--use-system-dns`   Include system/DHCP-assigned DNS servers as fallback

### System/DHCP fallback DNS

- On macOS/Linux, can optionally include DHCP-assigned DNS servers as fallback
- Use flag: `--use-system-dns` when running `docker-dns-updater.sh`
- Injects servers directly into dnsmasq configuration to avoid external blocking

## macOS Resolver Setup

- Uses `/etc/resolver/*.internal` to point `*.internal` to local dnsmasq
- Dynamic entries handled by `docker-dns-updater.py` (and system timer)

## Example Workflow

```bash
# Install everything
python3 /install.py

# Add a new container
docker run -d --name api nginx

# Refresh DNS for new container
python3 docker-dns-updater.py --force

# Test DNS resolution
ping api.internal
dig txt help.internal
```

## Quick Reference

### install.py

```text
--config=<docker|quad9|plain|all>   # What to install (default=all)
--update-profile                    # Re-download Quad9 profile (macOS only)
```

## Notes

- **Tailscale**: dynamic internal resolution always first
- **Quad9 DNS over TLS**: preferred fallback, supports IPv4/IPv6/HTTPS/TLS
- **Cloudflare Families**: secondary fallback (1.1.1.2, 1.0.0.2, etc.) if Quad9 is blocked
- DHCP/system-assigned DNS servers can be optionally included as fallback
- Config is idempotent: running multiple times won't duplicate entries
- Config changes automatically reload `dnsmasq`
