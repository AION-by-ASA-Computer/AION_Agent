#!/bin/sh
# aion-netjail: entrypoint of a custom MCP jail that has a network allowlist.
#
# Purpose: a customer-built MCP server may reach only the destinations listed in
# its allowlist (aion-mcp.yaml "network:", editable from the MCP Hub). The backend
# renders the nftables ruleset (src/mcp_custom/egress.py) and starts the container
# as root *of the container* with only NET_ADMIN, SETUID, SETGID and SETPCAP
# (src/security/container_policy.py, custom_mcp_jail_args). This script:
#   1. loads the ruleset into the container's own network namespace (never the
#      host's): everything not listed is refused, AION included;
#   2. becomes the unprivileged user with no capabilities at all and runs the
#      server ("$@", e.g. python -u server.py). The server's code can therefore
#      never change the rules.
# If the rules cannot be loaded the server is NOT started (fail closed).
#
# Inputs (environment, removed before the server starts):
#   AION_JAIL_NFT   nftables ruleset   AION_JAIL_UID / AION_JAIL_GID  target user
# stdout is the MCP channel: every message of this script goes to stderr.
set -eu

# Fixed PATH (same as the image's, /opt/venv first: that python has FastMCP) and
# absolute paths for the tools that run as root: nothing from the server's
# environment chooses which binary runs here. LD_* and the other reserved names
# never reach the container: the backend drops them before the start.
PATH=/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
NFT=/usr/sbin/nft
SETPRIV=/usr/bin/setpriv

fail() {
  echo "aion-netjail: $*" >&2
  exit 78
}

[ -n "${AION_JAIL_NFT:-}" ] || fail "no network rules received"
[ -x "$NFT" ] || fail "nftables missing from the sandbox image: update the aion-sandbox image"
uid="${AION_JAIL_UID:?}"
gid="${AION_JAIL_GID:?}"

# Load the rules. Kernels without the nft "reject" module refuse the ruleset:
# retry without the reject lines, the chains' "policy drop" still blocks
# everything not listed (refused connections then time out instead of failing fast).
if ! printf '%s\n' "$AION_JAIL_NFT" | "$NFT" -f - >&2 2>/tmp/aion-netjail.err; then
  printf '%s\n' "$AION_JAIL_NFT" | /usr/bin/grep -v ' reject ' | "$NFT" -f - >&2 \
    || { cat /tmp/aion-netjail.err >&2; fail "could not load the network rules: the server is not started"; }
fi
rm -f /tmp/aion-netjail.err

unset AION_JAIL_NFT AION_JAIL_UID AION_JAIL_GID
# Drop to the unprivileged user: no capabilities, empty bounding set, no way to
# regain privileges (no_new_privs).
exec "$SETPRIV" --reuid="$uid" --regid="$gid" --clear-groups \
  --inh-caps=-all --bounding-set=-all --no-new-privs -- "$@"
