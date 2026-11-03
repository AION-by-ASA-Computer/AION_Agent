"""GET /v1/client/bootstrap: profili/skill/MCP per i client Enterprise."""

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth_login import ChatAuthIdentity, require_chat_auth
from src.api.v1 import client_bootstrap as cb

SSE_BLOCK = {
    "execution": "client_remote",
    "auth": "aion_token",
    "transport": {"type": "sse", "url": "https://mcp.example.com/mcp/sse"},
}


def _profile(slug, skills, mcp, instructions="be nice", steps=20):
    return SimpleNamespace(
        slug=slug,
        name=slug.title(),
        description=f"{slug} desc",
        instructions=instructions,
        max_agent_steps=steps,
        skills=skills,
        mcp_servers=mcp,
        native_tool_groups=["files"],
        resolved_skills=lambda: list(skills),
    )


def _row(slug, mode="none", **kw):
    return SimpleNamespace(
        server_slug=slug,
        display_name=slug.upper(),
        description="d",
        category="knowledge",
        credential_mode=mode,
        **kw,
    )


class FakeSkills:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.metas = {}

    def add(self, name, content="---\nname: x\n---\nbody", status="verified"):
        p = self.tmp / f"{name}.md"
        p.write_text(content, encoding="utf-8")
        self.metas[name] = (
            {
                "name": name,
                "description": f"{name} d",
                "tags": ["t"],
                "version": 3,
                "status": status,
            },
            p,
        )

    def get_meta(self, name):
        m = self.metas.get(name)
        return dict(m[0]) if m else None

    def get_skill_path(self, name):
        m = self.metas.get(name)
        return m[1] if m else None


@pytest.fixture
def env(tmp_path, monkeypatch):
    skills = FakeSkills(tmp_path)
    for n in ("core", "doc", "other"):
        skills.add(n)
    st = SimpleNamespace(
        profiles=[
            _profile("alpha", ["core", "doc"], ["khub_rag", "memory"]),
            _profile("beta", ["other"], ["plane"]),
        ],
        allowed=None,
        rows=[_row("khub_rag"), _row("memory"), _row("plane"), _row("hidden")],
        registry={"khub_rag", "memory", "plane"},
        blocks={},
        skills=skills,
        auth=ChatAuthIdentity(user_row_id="u1", identifier="alice", via="chat_token"),
    )

    async def allowed(_uid):
        return st.allowed

    async def rows():
        return st.rows

    monkeypatch.setattr(cb, "_allowed_profile_slugs", allowed)
    monkeypatch.setattr(cb, "_enabled_mcp_rows", rows)
    monkeypatch.setattr(cb, "_registry_slugs", lambda: set(st.registry))
    monkeypatch.setattr(cb, "_client_block", lambda slug: st.blocks.get(slug))
    monkeypatch.setattr(cb, "_loaded_profiles", lambda: list(st.profiles))
    monkeypatch.setattr(cb, "_skill_registry", lambda: st.skills)
    monkeypatch.setattr(cb, "_profile_path", lambda slug: None)
    monkeypatch.delenv("AION_CLIENT_SYNC_INTERVAL_SEC", raising=False)

    app = FastAPI()
    app.include_router(cb.router, prefix="/v1")
    app.dependency_overrides[require_chat_auth] = lambda: st.auth
    st.client = TestClient(app)
    return st


def _get(env, **headers):
    return env.client.get("/v1/client/bootstrap", headers=headers)


def test_default_document_shape(env):
    r = _get(env)
    assert r.status_code == 200
    d = r.json()
    assert d["revision"].startswith("sha256:")
    assert r.headers["etag"] == f'"{d["revision"]}"'
    assert r.headers["cache-control"] == "private, no-cache"
    assert d["policy"] == {"sync_interval_sec": 900}
    a = next(p for p in d["profiles"] if p["slug"] == "alpha")
    assert a["instructions"] == "be nice" and a["max_agent_steps"] == 20
    assert a["skills"] == ["core", "doc"]
    assert a["mcp_servers"] == ["khub_rag", "memory"]
    assert a["native_tool_groups"] == ["files"]


def test_profiles_filtered_per_user_and_skills_limited(env):
    env.allowed = ["alpha"]
    d = _get(env).json()
    assert [p["slug"] for p in d["profiles"]] == ["alpha"]
    assert [s["name"] for s in d["skills"]] == ["core", "doc"]  # no "other"
    assert {m["slug"] for m in d["mcp_servers"]} == {"khub_rag", "memory"}  # no plane
    s = d["skills"][0]
    assert s["content"].startswith("---\nname: x") and s["version"] == 3


def test_api_key_caller_gets_all_profiles(env):
    env.auth = ChatAuthIdentity(via="api_key")
    env.allowed = None
    assert len(_get(env).json()["profiles"]) == 2


def test_skill_size_cap_and_status(env, caplog):
    env.skills.add("doc", content="x" * (cb.SKILL_MAX_BYTES + 1))
    env.skills.add("core", status="draft")
    with caplog.at_level("WARNING"):
        d = _get(env).json()
    assert [x["name"] for x in d["skills"]] == ["other"]
    assert "doc" in caplog.text
    a = next(p for p in d["profiles"] if p["slug"] == "alpha")
    assert a["skills"] == []


def test_mcp_default_server_only_and_visibility(env):
    d = _get(env).json()
    names = {m["slug"]: m for m in d["mcp_servers"]}
    assert set(names) == {"khub_rag", "memory", "plane"}  # "hidden" non referenziato
    for m in names.values():
        assert m["execution"] == "server_only" and m["auth"] == "none"
        assert "transport" not in m
    env.registry.discard("plane")
    assert "plane" not in {m["slug"] for m in _get(env).json()["mcp_servers"]}
    env.rows = [r for r in env.rows if r.server_slug != "memory"]
    assert "memory" not in {m["slug"] for m in _get(env).json()["mcp_servers"]}


def test_client_block_accepted(env):
    env.blocks["khub_rag"] = SSE_BLOCK
    m = next(x for x in _get(env).json()["mcp_servers"] if x["slug"] == "khub_rag")
    assert m["execution"] == "client_remote" and m["auth"] == "aion_token"
    assert m["transport"] == {"type": "sse", "url": "https://mcp.example.com/mcp/sse"}


def _with(**over):
    b = json.loads(json.dumps(SSE_BLOCK))
    for k, v in over.items():
        if k == "url":
            b["transport"]["url"] = v
        else:
            b[k] = v
    return b


STDIO = {
    "execution": "client_local",
    "auth": "none",
    "transport": {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "p"],
        "env": {"A": "b"},
    },
}


@pytest.mark.parametrize(
    "block,mode",
    [
        (_with(url="${KHUB_MCP_ENDPOINT}"), "none"),
        (_with(url="https://x.example.com/${X}"), "none"),
        (_with(execution="bogus"), "none"),
        (_with(auth="basic"), "none"),
        (_with(url="ftp://x.example.com"), "none"),
        (_with(url="https://u:p@x.example.com/sse"), "none"),
        (
            {**STDIO, "transport": {**STDIO["transport"], "env": {"API_TOKEN": "a"}}},
            "none",
        ),
        (
            {**STDIO, "transport": {**STDIO["transport"], "env": {"A": "${S}"}}},
            "none",
        ),
        ({**STDIO, "execution": "client_remote"}, "none"),
        (SSE_BLOCK, "per_user"),
        (SSE_BLOCK, "org_shared"),
        ("not a dict", "none"),
    ],
)
def test_client_block_rejected(env, block, mode):
    env.blocks["khub_rag"] = block
    env.rows = [_row("khub_rag", mode), _row("memory"), _row("plane")]
    m = next(x for x in _get(env).json()["mcp_servers"] if x["slug"] == "khub_rag")
    assert m["execution"] == "server_only" and m["auth"] == "none"
    assert "transport" not in m


def test_stdio_block_accepted(env):
    env.blocks["memory"] = STDIO
    m = next(x for x in _get(env).json()["mcp_servers"] if x["slug"] == "memory")
    assert m["execution"] == "client_local"
    assert m["transport"]["command"] == "npx"


def test_etag_304_and_stable(env):
    r1 = _get(env)
    etag = r1.headers["etag"]
    r2 = _get(env)
    assert r2.headers["etag"] == etag
    assert r2.json()["revision"] == r1.json()["revision"]
    r3 = _get(env, **{"If-None-Match": etag})
    assert r3.status_code == 304 and r3.content == b""
    assert r3.headers["etag"] == etag
    assert r3.headers["cache-control"] == "private, no-cache"
    assert _get(env, **{"If-None-Match": f"W/{etag}"}).status_code == 304
    assert _get(env, **{"If-None-Match": '"sha256:other"'}).status_code == 200


def test_etag_changes_with_instructions(env):
    etag = _get(env).headers["etag"]
    env.profiles[0].instructions = "changed"
    r = _get(env, **{"If-None-Match": etag})
    assert r.status_code == 200 and r.headers["etag"] != etag


def test_sync_interval_env(env, monkeypatch):
    monkeypatch.setenv("AION_CLIENT_SYNC_INTERVAL_SEC", "10")
    assert _get(env).json()["policy"]["sync_interval_sec"] == 60
    monkeypatch.setenv("AION_CLIENT_SYNC_INTERVAL_SEC", "1200")
    assert _get(env).json()["policy"]["sync_interval_sec"] == 1200
    monkeypatch.setenv("AION_CLIENT_SYNC_INTERVAL_SEC", "abc")
    assert _get(env).json()["policy"]["sync_interval_sec"] == 900


def test_unauthenticated_is_401(monkeypatch):
    monkeypatch.setenv("AION_CHAT_AUTH_SECRET", "x" * 40)
    monkeypatch.delenv("AION_CHAT_ALLOW_ANONYMOUS", raising=False)
    from src.api.main import app

    r = TestClient(app).get("/v1/client/bootstrap")
    assert r.status_code == 401


def test_route_registered():
    from src.api.main import app

    assert "/v1/client/bootstrap" in {r.path for r in app.routes if hasattr(r, "path")}


def test_registry_get_client_block_tolerant(tmp_path):
    import yaml

    from src.mcp_manager import MCPManager
    from src.mcp_registry_io import load_registry_file

    p = tmp_path / "reg.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "a": {"type": "sse", "url": "https://x", "client": SSE_BLOCK},
                "b": {"command": "python", "client": "oops"},
                "c": {"command": "python"},
            }
        )
    )
    flat = load_registry_file(str(p))
    assert flat["a"]["url"] == "https://x" and flat["a"]["client"] == SSE_BLOCK
    mgr = MCPManager.__new__(MCPManager)
    mgr._registry = flat
    assert mgr.get_client_block("a") == SSE_BLOCK
    assert mgr.get_client_block("b") is None
    assert mgr.get_client_block("c") is None
    assert mgr.get_client_block("missing") is None
