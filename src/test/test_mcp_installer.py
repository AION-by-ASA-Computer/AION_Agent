import asyncio

from src.runtime.mcp_installer import mcp_installer


def test_install_stdio_returns_clear_message():
    ok, msg = asyncio.run(
        mcp_installer.install_from_market({"id": "mcp:test", "install_type": "stdio"})
    )
    assert ok is False
    assert "stdio" in msg.lower() or "manuale" in msg.lower()


def test_install_unknown_type():
    ok, msg = asyncio.run(
        mcp_installer.install_from_market({"id": "x", "install_type": "weird"})
    )
    assert ok is False
    assert "non supportato" in msg.lower() or "weird" in msg


def test_install_remote_type():
    ok, msg = asyncio.run(
        mcp_installer.install_from_market({"id": "x", "install_type": "remote"})
    )
    assert ok is True
    assert msg == ""


def test_market_safe_dir_name_sanitizes():
    from src.runtime.mcp_installer import market_safe_dir_name

    assert market_safe_dir_name({"name": "Foo/Bar"}) == "foo_bar"
    assert market_safe_dir_name({"name": "a::b"}) == "a_b"


def test_git_npm_build_preflight_detects_publish_only_repo(tmp_path):
    from src.runtime.mcp_installer import _git_npm_build_preflight

    root = tmp_path / "repo"
    root.mkdir()
    (root / "package.json").write_text(
        '{"name": "@scope/pkg", "scripts": {"prepare": "npm run build", "build": "tsc"}}',
        encoding="utf-8",
    )
    msg = _git_npm_build_preflight(root)
    assert msg is not None
    assert "tsconfig" in msg.lower()
    assert "npx" in msg.lower()


def test_git_npm_build_preflight_ok_when_tsconfig_present(tmp_path):
    from src.runtime.mcp_installer import _git_npm_build_preflight

    root = tmp_path / "repo"
    root.mkdir()
    (root / "package.json").write_text(
        '{"scripts": {"build": "tsc"}}',
        encoding="utf-8",
    )
    (root / "tsconfig.json").write_text("{}", encoding="utf-8")
    assert _git_npm_build_preflight(root) is None


def test_npm_log_meaningful_excerpt_finds_stack(tmp_path):
    from src.runtime.mcp_installer import _npm_log_meaningful_excerpt

    log = tmp_path / "npm-debug.log"
    noise = "\n".join([f"{i} silly fetch http cache foo-{i}" for i in range(100)])
    tail = "\n".join(
        [
            "2000 warn deprecated x",
            "2143 verbose stack Error: command failed",
            "2144 verbose stack at promiseSpawn (...)",
            "2147 error code 1",
            "2148 error command sh -c npm run build",
        ]
    )
    log.write_text(noise + "\n" + tail, encoding="utf-8")
    ex = _npm_log_meaningful_excerpt(log)
    assert "verbose stack" in ex
    assert "error code" in ex
    assert "http cache foo-0" not in ex
