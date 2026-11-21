"""Network allowlist of customer-built MCP servers ("closed by default").

A custom MCP server has no network unless its allowlist names the destinations it
may reach (``network:`` in ``aion-mcp.yaml``, editable by the admin from the MCP
Hub). Everything else, AION itself included, stays unreachable.

The allowlist is enforced **inside the jail's own network namespace**, never on
the host: the container starts with the minimum capabilities, the image's
``aion-netjail`` entrypoint (``docker/sandbox-netjail.sh``) loads the nftables
ruleset rendered here, then drops every capability before running the server.
Nothing has to be installed or configured on the host.

This module is the single place of the logic, used by:
- the manifest and the admin endpoint (``parse_allowlist``: validation);
- the spawn policy (``resolve`` + ``render_nft``: what the jail may reach).

Entry format (one string each)::

    as400.azienda.local:446,449,8470-8476   # host name, ports and port ranges
    10.20.0.0/24:5432                        # IPv4 address or subnet
    api.example.com                          # no ports: every port of that host
    [fd00::10]:443  /  fd00::/64             # IPv6 (brackets when ports are given)

Host names are resolved by the backend when the jail starts and pinned with
``--add-host``; DNS stays blocked inside the jail, so a name that is not in the
list cannot be resolved (and DNS cannot be used to leak data). Wildcards
(``*.example.com``) are not supported: list exact names or subnets.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple, Union

# Upper bound of entries per server: the list is meant for a handful of company
# systems, a long list usually means "open everything", which this model refuses.
MAX_ENTRIES = 50

# Longest accepted entry (253-char host name + a port list): longer input is refused
# before parsing, so no entry can make validation slow.
MAX_ENTRY_LENGTH = 300

# Cloud metadata endpoints hand out the credentials of the virtual machine: they
# stay blocked even when an entry (e.g. a wide subnet) would include them.
_METADATA_V4 = ipaddress.ip_network("169.254.0.0/16")
_METADATA_V6 = ipaddress.ip_network("fd00:ec2::254/128")

# RFC 1123 host name: dot-separated labels of letters, digits and hyphens.
_LABEL_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")

IpNetwork = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]
PortRange = Tuple[int, int]


class AllowlistError(ValueError):
    """An allowlist entry is not valid; the message is shown to the admin as is."""


@dataclass(frozen=True)
class AllowEntry:
    """One validated allowlist entry.

    ``host``: lower-case host name, or ``None`` for an IP/subnet entry.
    ``network``: the IP/subnet for IP entries, ``None`` for host names.
    ``ports``: inclusive port ranges; empty means every port.
    """

    host: Optional[str]
    network: Optional[IpNetwork]
    ports: Tuple[PortRange, ...]

    def __str__(self) -> str:
        """Canonical text form, stored in the registry and shown in the Hub."""
        if self.host:
            target = self.host
        elif self.network is not None and self.network.num_addresses == 1:
            target = str(self.network.network_address)
        else:
            target = str(self.network)
        if not self.ports:
            return target
        if self.network is not None and self.network.version == 6:
            target = f"[{target}]"
        return f"{target}:{_ports_text(self.ports)}"


@dataclass
class ResolvedEgress:
    """What a jail may reach, ready for the container argv.

    ``rules``: (network, ports) pairs rendered by ``render_nft``.
    ``hosts``: (name, ip) pairs pinned in the jail's ``/etc/hosts``.
    ``warnings``: names that could not be resolved (shown by the upload check).
    """

    rules: List[Tuple[IpNetwork, Tuple[PortRange, ...]]] = field(default_factory=list)
    hosts: List[Tuple[str, str]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _ports_text(ports: Sequence[PortRange]) -> str:
    """``((446, 446), (8470, 8476))`` -> ``"446,8470-8476"``."""
    return ",".join(str(a) if a == b else f"{a}-{b}" for a, b in ports)


def _parse_ports(text: str, entry: str) -> Tuple[PortRange, ...]:
    """Parse ``"446,449,8470-8476"`` into sorted, de-duplicated inclusive ranges."""
    ranges: List[PortRange] = []
    for part in text.split(","):
        part = part.strip()
        m = re.fullmatch(r"(\d{1,5})(?:-(\d{1,5}))?", part)
        if not m:
            raise AllowlistError(
                f"'{entry}': invalid port '{part}' (use 443, or 8470-8476)"
            )
        lo = int(m.group(1))
        hi = int(m.group(2) or lo)
        if not (1 <= lo <= hi <= 65535):
            raise AllowlistError(
                f"'{entry}': ports must be between 1 and 65535 (and ranges ascending)"
            )
        ranges.append((lo, hi))
    return tuple(sorted(set(ranges)))


def _parse_host(text: str, entry: str) -> Tuple[Optional[str], Optional[IpNetwork]]:
    """Return (host name, None) or (None, network) for the target part of an entry."""
    try:
        return None, ipaddress.ip_network(text, strict=False)
    except ValueError:
        pass
    name = text.lower().rstrip(".")
    if "*" in name:
        raise AllowlistError(
            f"'{entry}': wildcards are not supported, list the exact host names"
        )
    if (
        "/" in name
        or len(name) > 253
        or not all(_LABEL_RE.match(label) for label in name.split("."))
    ):
        raise AllowlistError(f"'{entry}': not a valid host name, IP address or subnet")
    return name, None


def parse_entry(raw: str) -> AllowEntry:
    """Validate one entry (see the module docstring for the format)."""
    entry = str(raw or "").strip()
    if not entry:
        raise AllowlistError("empty entry")
    # Entries come from uploads and admin edits: bound the length before any parsing
    # (a host name is at most 253 chars, plus a port list).
    if len(entry) > MAX_ENTRY_LENGTH:
        raise AllowlistError(f"entry longer than {MAX_ENTRY_LENGTH} characters")
    ports_text: Optional[str] = None
    if entry.startswith("["):
        # [IPv6]:ports, split with plain string operations (no regex backtracking).
        target, sep, rest = entry[1:].partition("]")
        if not sep or not target or (rest and not rest.startswith(":")):
            raise AllowlistError(f"'{entry}': write IPv6 with ports as [address]:port")
        ports_text = rest[1:] if rest else None
    elif entry.count(":") == 1:
        target, ports_text = entry.split(":")
    else:
        # No colon, or a bare IPv6 address/subnet (several colons, no ports).
        target = entry
    host, network = _parse_host(target.strip(), entry)
    ports = _parse_ports(ports_text, entry) if ports_text is not None else ()
    return AllowEntry(host=host, network=network, ports=ports)


def parse_allowlist(entries: Optional[Iterable[str]]) -> List[AllowEntry]:
    """Validate a whole list, keeping its order and dropping duplicates.

    Raises ``AllowlistError`` on the first invalid entry or above ``MAX_ENTRIES``.
    """
    out: List[AllowEntry] = []
    seen = set()
    for index, raw in enumerate(entries or []):
        # Refuse a huge list early instead of parsing every entry first (duplicates
        # count here too: a legitimate list stays far below this bound).
        if index >= MAX_ENTRIES * 4:
            raise AllowlistError(f"at most {MAX_ENTRIES} network entries per server")
        parsed = parse_entry(raw)
        key = str(parsed)
        if key not in seen:
            seen.add(key)
            out.append(parsed)
    if len(out) > MAX_ENTRIES:
        raise AllowlistError(f"at most {MAX_ENTRIES} network entries per server")
    return out


def normalize_allowlist(entries: Optional[Iterable[str]]) -> List[str]:
    """Validated canonical strings, as stored in the registry."""
    return [str(e) for e in parse_allowlist(entries)]


def resolve(entries: Sequence[AllowEntry]) -> ResolvedEgress:
    """Turn entries into IP rules, resolving host names now (at jail start).

    Side effect: DNS lookups through the backend's resolver (the company DNS).
    A name that does not resolve is skipped with a warning: the server still
    starts, and its connections to that name fail.
    """
    out = ResolvedEgress()
    for entry in entries:
        if entry.network is not None:
            out.rules.append((entry.network, entry.ports))
            continue
        try:
            infos = socket.getaddrinfo(entry.host, None, proto=socket.IPPROTO_TCP)
        except OSError:
            out.warnings.append(
                f"{entry.host}: the name does not resolve, connections to it will fail"
            )
            continue
        addresses = sorted({info[4][0].split("%")[0] for info in infos})
        for addr in addresses:
            ip = ipaddress.ip_address(addr)
            out.rules.append((ipaddress.ip_network(ip), entry.ports))
            out.hosts.append((str(entry.host), str(ip)))
    return out


def render_nft(rules: Sequence[Tuple[IpNetwork, Tuple[PortRange, ...]]]) -> str:
    """nftables ruleset of a jail: allowlisted destinations only, then refuse.

    Only ``ipaddress`` objects and integers reach the text (no free-form strings),
    so an entry cannot inject nftables syntax. The ``reject`` lines make refused
    connections fail at once instead of hanging; ``aion-netjail`` drops them (and
    keeps ``policy drop``) on kernels without the reject module.
    """
    allow_lines = []
    for network, ports in rules:
        family = "ip" if network.version == 4 else "ip6"
        match = f"{family} daddr {network}"
        if ports:
            match += (
                " meta l4proto { tcp, udp } th dport { "
                + ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in ports)
                + " }"
            )
        allow_lines.append(f"    {match} accept")
    lines = [
        "table inet aion_jail {",
        "  chain output {",
        "    type filter hook output priority filter; policy drop;",
        '    oifname "lo" accept',
        "    ct state established,related accept",
        "    # Cloud metadata: never reachable, whatever the entries say",
        f"    ip daddr {_METADATA_V4} drop",
        f"    ip6 daddr {_METADATA_V6} drop",
        *allow_lines,
        "    meta l4proto tcp reject with tcp reset",
        "    reject with icmpx admin-prohibited",
        "  }",
        "  chain input {",
        "    type filter hook input priority filter; policy drop;",
        '    iifname "lo" accept',
        "    ct state established,related accept",
        "  }",
        "}",
    ]
    return "\n".join(lines) + "\n"
