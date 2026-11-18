"""Network of custom MCP jails: closed by default, open only to the allowlist.

Covers the allowlist parser and nftables rendering (src/mcp_custom/egress.py), the
jail flags per engine (container_policy.custom_mcp_jail_args), the precedence of
manifest vs admin list and the admin edit, plus the company CA bundle and the
corporate proxy in the dependency build.
"""

from __future__ import annotations

import asyncio
import ipaddress
from pathlib import Path

import pytest

import src.aion_env  # noqa: F401
from src.mcp_custom import egress
from src.mcp_custom.egress import AllowlistError, ResolvedEgress, normalize_allowlist, parse_entry, render_nft
from src.mcp_custom.manifest import ManifestError, parse_manifest_data
from src.security.container_policy import (
    CUSTOM_MCP_CA_PATH,
    NETJAIL_ENTRYPOINT,
    build_custom_mcp_deps_argv,
    build_custom_mcp_run_argv,
    custom_mcp_jail_args,
)

_BASE_MANIFEST = {"aion_mcp": 1, "slug": "net_srv", "name": "N", "description": "d", "version": "1.0.0"}


def _egress(*pairs) -> ResolvedEgress:
    """ResolvedEgress for (cidr, ports) pairs without touching DNS."""
    return ResolvedEgress(rules=[(ipaddress.ip_network(net), ports) for net, ports in pairs])


# ───────────────────────── parser ─────────────────────────


@pytest.mark.parametrize(
    "raw,canonical",
    [
        ("as400.azienda.local:446,449,8470-8476", "as400.azienda.local:446,449,8470-8476"),
        ("CRM.Azienda.Local.:443", "crm.azienda.local:443"),  # lower case, trailing dot dropped
        ("10.20.0.0/24:5432", "10.20.0.0/24:5432"),
        ("10.20.0.7/24", "10.20.0.0/24"),  # host bits normalized
        ("192.168.1.5", "192.168.1.5"),  # single address shown without /32
        ("api.example.com", "api.example.com"),  # no ports = every port
        ("[fd00::10]:443", "[fd00::10]:443"),
        ("fd00::/64", "fd00::/64"),
        ("host.local:443,80,443", "host.local:80,443"),  # sorted, de-duplicated
    ],
)
def test_parse_valid_entries(raw: str, canonical: str):
    """Valid entries are accepted and stored in one canonical form."""
    assert str(parse_entry(raw)) == canonical


@pytest.mark.parametrize(
    "raw",
    ["", "*.example.com", "host:0", "host:70000", "host:90-80", "host:abc", "bad host", "-x.local", "fd00::1:443:80x"],
)
def test_parse_rejects_invalid_entries(raw: str):
    """Wildcards, bad ports and malformed hosts are refused with a readable error."""
    with pytest.raises(AllowlistError):
        parse_entry(raw)


def test_allowlist_dedup_and_limit():
    """Duplicates collapse; more than MAX_ENTRIES distinct entries is refused."""
    assert normalize_allowlist(["a.local:443", "A.local:443"]) == ["a.local:443"]
    with pytest.raises(AllowlistError):
        normalize_allowlist([f"10.0.{i // 250}.{i % 250}" for i in range(egress.MAX_ENTRIES + 1)])


def test_resolve_pins_names_and_warns_on_unknown(monkeypatch: pytest.MonkeyPatch):
    """Names become IP rules + /etc/hosts pins; an unresolvable name is only a warning."""

    def fake_getaddrinfo(host, *_a, **_k):
        if host == "crm.azienda.local":
            return [(None, None, None, "", ("10.1.2.3", 0))]
        raise OSError("not found")

    monkeypatch.setattr(egress.socket, "getaddrinfo", fake_getaddrinfo)
    out = egress.resolve(egress.parse_allowlist(["crm.azienda.local:443", "ghost.local", "10.9.0.0/16"]))
    assert out.hosts == [("crm.azienda.local", "10.1.2.3")]
    assert [str(net) for net, _ in out.rules] == ["10.1.2.3/32", "10.9.0.0/16"]
    assert out.warnings and "ghost.local" in out.warnings[0]


# ───────────────────────── nftables ─────────────────────────


def test_render_nft_allows_only_the_list():
    """Default drop, metadata always dropped, listed IPs/ports accepted, the rest refused."""
    text = render_nft(_egress(("10.1.2.3/32", ((446, 446), (8470, 8476))), ("fd00::/64", ())).rules)
    assert "policy drop" in text and "table inet aion_jail" in text
    assert "ip daddr 169.254.0.0/16 drop" in text
    assert "ip daddr 10.1.2.3/32 meta l4proto { tcp, udp } th dport { 446, 8470-8476 } accept" in text
    assert "ip6 daddr fd00::/64 accept" in text
    # Metadata drop comes before any allow rule (a wide subnet cannot reopen it).
    assert text.index("169.254.0.0/16") < text.index("10.1.2.3")
    assert text.rstrip().endswith("}")


# ───────────────────────── jail flags ─────────────────────────


@pytest.mark.parametrize("runtime", ["docker", "podman"])
def test_no_allowlist_means_no_network(runtime: str):
    """Empty allowlist: --network=none, no extra capability, python run directly."""
    flags, command = custom_mcp_jail_args(runtime, None)
    assert "--network=none" in flags
    assert not any(f.startswith("--cap-add") for f in flags)
    assert command == ["python"]
    flags, command = custom_mcp_jail_args(runtime, ResolvedEgress())
    assert "--network=none" in flags and command == ["python"]


def test_allowlist_on_docker_uses_netjail():
    """Allowlist: bridge, minimal caps, pinned hosts, DNS to loopback, aion-netjail drops to 65534."""
    resolved = _egress(("10.1.2.3/32", ((443, 443),)))
    resolved.hosts = [("crm.azienda.local", "10.1.2.3")]
    flags, command = custom_mcp_jail_args("docker", resolved)
    assert "--network=bridge" in flags and "--network=none" not in flags
    assert {f for f in flags if f.startswith("--cap-add")} == {
        "--cap-add=NET_ADMIN",
        "--cap-add=SETUID",
        "--cap-add=SETGID",
        "--cap-add=SETPCAP",
    }
    assert flags[flags.index("--user") + 1] == "0:0"
    assert flags[flags.index("--add-host") + 1] == "crm.azienda.local:10.1.2.3"
    assert flags[flags.index("--dns") + 1] == "127.0.0.1"
    assert "AION_JAIL_UID=65534" in flags and "AION_JAIL_GID=65534" in flags
    assert any(f.startswith("AION_JAIL_NFT=") and "10.1.2.3/32" in f for f in flags)
    assert command == [NETJAIL_ENTRYPOINT, "python"]


def test_allowlist_on_podman_keeps_userns_and_engine_network(monkeypatch: pytest.MonkeyPatch):
    """Podman keep-id: the userns mapping stays, root at start, netjail drops to the host uid."""
    monkeypatch.setenv("AION_SANDBOX_HOST_DATA_DIR", "/srv/aion/data")
    monkeypatch.setenv("AION_SANDBOX_HOST_UID", "1001")
    monkeypatch.setenv("AION_SANDBOX_HOST_GID", "1002")
    monkeypatch.delenv("AION_SANDBOX_CONTAINER_USERNS", raising=False)
    flags, _ = custom_mcp_jail_args("podman", _egress(("10.0.0.0/8", ())))
    assert "--userns=keep-id" in flags
    assert not any(f.startswith("--network") for f in flags)  # engine default (pasta/slirp4netns)
    assert "AION_JAIL_UID=1001" in flags and "AION_JAIL_GID=1002" in flags


def test_run_argv_with_allowlist_and_ca_mount():
    """Full argv: netjail entrypoint, then python -u <entrypoint>; CA mounted read-only."""
    argv = build_custom_mcp_run_argv(
        runtime="docker",
        image="aion/sandbox:latest",
        slug="net_srv",
        host_server_dir=Path("/h/custom/net_srv"),
        egress=_egress(("10.1.2.3/32", ())),
        host_ca_bundle=Path("/h/custom/.ca/ca-bundle.pem"),
    )
    assert argv[argv.index("--entrypoint") + 1] == NETJAIL_ENTRYPOINT
    assert argv[-4:] == ["aion/sandbox:latest", "python", "-u", "server.py"]
    assert any(a.endswith(f":{CUSTOM_MCP_CA_PATH}:ro") for a in argv)


# ───────────────────────── manifest + admin ─────────────────────────


def test_manifest_network_is_validated():
    """The manifest list is normalized; invalid entries or a non-list are refused."""
    m = parse_manifest_data({**_BASE_MANIFEST, "network": ["CRM.local:443", "crm.local:443"]})
    assert m.network == ["crm.local:443"]
    assert parse_manifest_data(dict(_BASE_MANIFEST)).network == []
    with pytest.raises(ManifestError):
        parse_manifest_data({**_BASE_MANIFEST, "network": ["*.example.com"]})
    with pytest.raises(ManifestError):
        parse_manifest_data({**_BASE_MANIFEST, "network": "lan"})


def test_network_choice_precedence():
    """The admin's list survives uploads; otherwise the manifest's list applies."""
    from src.mcp_custom.install import _network_choice

    plain = parse_manifest_data(dict(_BASE_MANIFEST))
    listed = parse_manifest_data({**_BASE_MANIFEST, "network": ["crm.local:443"]})
    assert _network_choice(plain, None) == ([], "manifest")
    assert _network_choice(listed, None) == (["crm.local:443"], "manifest")
    admin_prev = {"command": "python", "aion_custom": {"network": ["10.0.0.5"], "network_source": "admin"}}
    assert _network_choice(listed, admin_prev) == (["10.0.0.5"], "admin")


def test_runtime_allowlist_fails_closed():
    """A non-list or invalid registry value means no network, never unchecked rules."""
    from src.mcp_custom.runtime import network_allowlist

    assert network_allowlist({"aion_custom": {"network": "lan"}}) == []
    assert network_allowlist({"aion_custom": {"network": ["*.x.com"]}}) == []
    assert network_allowlist({"aion_custom": {"network": ["crm.local:443"]}}) == ["crm.local:443"]
    assert network_allowlist(None, ["10.0.0.1"]) == ["10.0.0.1"]


def test_admin_sets_network_allowlist(monkeypatch: pytest.MonkeyPatch):
    """PUT network: registry updated as an admin list, workers restarted, change audited."""
    from unittest.mock import AsyncMock

    from src.mcp_custom import install
    from src.mcp_manager import mcp_manager

    entry = {"command": "python", "aion_custom": {"name": "N", "version": "1.0.0", "network": [], "network_source": "manifest"}}
    registry = {"net_srv": entry}
    monkeypatch.setattr(mcp_manager, "load_registry", lambda *a, **k: None)
    monkeypatch.setattr(mcp_manager, "_registry", registry)
    monkeypatch.setattr(mcp_manager, "_registry_local", {})
    monkeypatch.setattr(mcp_manager, "_rebuild_merged", lambda: registry.update(mcp_manager._registry_local))
    monkeypatch.setattr(mcp_manager, "save_registry", lambda: None)
    invalidate, audit = AsyncMock(), AsyncMock()
    monkeypatch.setattr(install, "invalidate_runtime", invalidate)
    monkeypatch.setattr(install, "_audit", audit)

    out = asyncio.run(install.set_network_allowlist("net_srv", ["CRM.local:443"], actor="admin"))

    assert out == {"server_slug": "net_srv", "network": ["crm.local:443"], "network_source": "admin"}
    assert registry["net_srv"]["aion_custom"]["network"] == ["crm.local:443"]
    invalidate.assert_awaited_once_with("net_srv")
    assert audit.await_args.args[1] == "mcp_custom.network"
    with pytest.raises(install.ActivationError):
        asyncio.run(install.set_network_allowlist("net_srv", ["*.bad"], actor="admin"))


# ───────────────────────── build, CA, proxy ─────────────────────────


def test_build_argv_forwards_proxy_and_ca(monkeypatch: pytest.MonkeyPatch):
    """The dependency build uses the corporate proxy (by name) and trusts the company CA."""
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.azienda.local:3128")
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    argv = build_custom_mcp_deps_argv(
        runtime="docker",
        image="aion/sandbox:latest",
        slug="net_srv",
        host_src_dir=Path("/h/custom/.staging/x/src"),
        host_deps_dir=Path("/h/custom/.deps/k"),
        requirements_rel=".aion-requirements.txt",
        host_ca_bundle=Path("/h/custom/.ca/ca-bundle.pem"),
    )
    assert argv[argv.index("HTTPS_PROXY") - 1] == "-e"  # value comes from the CLI env
    assert "HTTP_PROXY" not in argv  # unset variables are not forwarded
    assert not any("proxy.azienda.local" in a for a in argv)
    assert f"PIP_CERT={CUSTOM_MCP_CA_PATH}" in argv


def test_ca_bundle_combines_public_roots_and_company_ca(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """The jail bundle keeps the public roots (internet still works) and adds the company CA."""
    from src.mcp_custom import ca

    company = tmp_path / "azienda.pem"
    company.write_text("-----BEGIN CERTIFICATE-----\nAZIENDA\n-----END CERTIFICATE-----\n", encoding="utf-8")
    monkeypatch.setenv("AION_SANDBOX_CA_BUNDLE", str(company))
    monkeypatch.setattr(ca, "custom_root", lambda: tmp_path / "custom")
    # Keep the CA uploaded from the panel (data volume) out of the test.
    monkeypatch.setattr("src.security.company_ca.store_dir", lambda: tmp_path / "network")
    ca._last.clear()

    bundle = ca.jail_ca_bundle()

    text = bundle.read_text(encoding="utf-8")
    assert "AZIENDA" in text and text.count("BEGIN CERTIFICATE") > 10
    assert ca.ca_env("/etc/aion/ca-bundle.pem")["REQUESTS_CA_BUNDLE"] == "/etc/aion/ca-bundle.pem"


def test_ca_bundle_absent_or_invalid_is_ignored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """No variable, a missing file or a non-PEM file: jails keep the public roots only."""
    from src.mcp_custom import ca

    monkeypatch.setattr(ca, "custom_root", lambda: tmp_path / "custom")
    # Keep the CA uploaded from the panel (data volume) out of the test.
    monkeypatch.setattr("src.security.company_ca.store_dir", lambda: tmp_path / "network")
    ca._last.clear()
    monkeypatch.delenv("AION_SANDBOX_CA_BUNDLE", raising=False)
    assert ca.jail_ca_bundle() is None
    monkeypatch.setenv("AION_SANDBOX_CA_BUNDLE", str(tmp_path / "missing.pem"))
    assert ca.jail_ca_bundle() is None
    bad = tmp_path / "bad.pem"
    bad.write_text("not a certificate", encoding="utf-8")
    monkeypatch.setenv("AION_SANDBOX_CA_BUNDLE", str(bad))
    assert ca.jail_ca_bundle() is None


def test_jail_env_points_tls_to_mounted_bundle():
    """In the jail the TLS variables point to the mounted bundle path."""
    from src.mcp_custom.runtime import finalize_process_env

    env = finalize_process_env({}, in_container=True, deps_dir=None, ca_path=Path("/whatever/ca-bundle.pem"))
    assert env["SSL_CERT_FILE"] == CUSTOM_MCP_CA_PATH and env["NODE_EXTRA_CA_CERTS"] == CUSTOM_MCP_CA_PATH
