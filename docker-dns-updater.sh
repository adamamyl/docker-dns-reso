#!/usr/bin/env bash
set -euo pipefail

DEBUG=0 DRY_RUN=0 FORCE=0 QUIET=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --debug)   DEBUG=1 ;;
        --dry-run) DRY_RUN=1 ;;
        --force)   FORCE=1 ;;
        --quiet)   QUIET=1 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
    shift
done

[[ $DEBUG -eq 1 ]] && set -x

OS="$(uname)"
DNS_FILE="/etc/dnsmasq.d/docker-hosts.conf"
[[ "$OS" == "Darwin" ]] && DNS_FILE="$(brew --prefix)/etc/dnsmasq.d/docker-hosts.conf"

TMP="$(mktemp)"
declare -A SEEN

log() { [[ $QUIET -eq 0 ]] && echo "$@"; }

CONTAINERS="$(docker ps -q || true)"
[[ -z "$CONTAINERS" ]] && exit 0

for ID in $CONTAINERS; do
    JSON="$(docker inspect "$ID")"
    NAME="$(jq -r '.[0].Name | ltrimstr("/")' <<<"$JSON")"
    NETS="$(jq -r '.[0].NetworkSettings.Networks | keys[]' <<<"$JSON")"

    for NET in $NETS; do
        IP4="$(jq -r --arg n "$NET" \
            'try .[0].NetworkSettings.Networks[$n].IPAddress // empty' <<<"$JSON")"
        IP6="$(jq -r --arg n "$NET" \
            'try .[0].NetworkSettings.Networks[$n].GlobalIPv6Address // empty' <<<"$JSON")"

        HOST="$NAME.internal"
        [[ -n "${SEEN[$NAME]+x}" ]] && HOST="$NAME.$NET.internal"
        SEEN["$NAME"]=1

        [[ -n "$IP4" ]] && echo "address=/$HOST/$IP4" >>"$TMP"
        [[ -n "$IP6" ]] && echo "address=/$HOST/$IP6" >>"$TMP"
    done
done

[[ $DRY_RUN -eq 1 ]] && { cat "$TMP"; rm "$TMP"; exit 0; }

if [[ ! -f "$DNS_FILE" ]] || [[ $FORCE -eq 1 ]] || ! cmp -s "$TMP" "$DNS_FILE"; then
    sudo install -m 644 "$TMP" "$DNS_FILE"
    log "Reloading dnsmasq"
    [[ "$OS" == "Darwin" ]] && brew services restart dnsmasq || sudo systemctl reload dnsmasq
fi

rm -f "$TMP"
