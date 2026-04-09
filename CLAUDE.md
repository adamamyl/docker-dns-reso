# docker-dns-reso — Claude Code conventions

## What this project does

Local Docker + Tailscale + VPN DNS routing via dnsmasq and macOS `/etc/resolver/` profiles.
Resolves `*.internal` hostnames from running Docker containers, with Quad9 DoT fallback.

## Repo layout

```
docker-dns-updater.py   Main updater script (run manually or via cron/systemd)
install.py              Interactive installer (macOS + Linux)
dnsmasq/                dnsmasq config fragments
macos/                  macOS-specific resolver profiles and launchd plists
systemd/                systemd-resolved config (Linux)
net_tester/             Diagnostic tool — see net_tester/dev-setup.md
  coordinator.py        Entry point: runs all diagnostic modules
  modules/              Individual check modules (resolver, arp, mdns, quad9, …)
  dev-sast              SAST + lint script (ruff, mypy, bandit)
```

## Tech stack

- Python 3.11+, standard library only for runtime scripts
- `uv` for package management in net_tester — never raw `pip`
- `rich` for net_tester output
- dnsmasq, macOS scutil/mDNSResponder, systemd-resolved

## Running the diagnostic tool

```bash
# Full suite
uv run python net_tester/coordinator.py

# Quick ARP/networking check only (no Docker needed)
uv run python net_tester/coordinator.py --arp-only

# Skip slow Docker check
uv run python net_tester/coordinator.py --skip docker_dns

# Dry run (no external commands executed)
uv run python net_tester/coordinator.py --dry-run
```

Snapshots saved to `net_tester/snapshots/run-<timestamp>/diagnostic.json`.

## SAST / linting (net_tester only)

```bash
net_tester/dev-sast
```

Runs ruff check, ruff format, mypy, bandit against `net_tester/` and top-level scripts.
All checks must pass before committing. Pre-commit hooks enforce this.

Config lives in `pyproject.toml` at repo root.

## Known issues / context

- macOS 26.x alpha/beta builds regress local-subnet ARP — `--arp-only` will flag this
- NordVPN Threat Protection (`com.nordvpn.macos.Shield`) endpoint-security extension
  can silently drop outbound same-subnet packets even when NordVPN is disconnected
- UniFi "Multicast to Unicast" WiFi option breaks ARP between WiFi and wired clients
  on the same VLAN after the AP loses its learned client table (e.g. power cut)
- macOS `/etc/resolver/` supplemental DNS is broken in some Tahoe 26.x alpha builds —
  this is what the resolver/mdns/quad9 modules detect

## Git workflow

Follows global conventions (see `~/.claude/CLAUDE.md`):
- Branch from `main`, never commit directly
- Conventional commits: `feat(scope):` / `fix(scope):` / `chore:`
- PRs to merge; pre-commit hooks enforce ruff, mypy, bandit, gitleaks
