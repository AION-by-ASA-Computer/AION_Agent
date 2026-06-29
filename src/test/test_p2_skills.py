"""P2 Sprint 4 — skill distill, search draft filter, admin promote."""
import textwrap
from pathlib import Path

import frontmatter

from src.learning.skill_distiller import SkillDistiller
from src.skill_registry import SkillRegistry


def test_skill_distill_includes_tool_calls():
    d = SkillDistiller()
    log = [
        {"type": "tool_start", "name": "web_search", "arguments": {"q": "test"}},
        {"type": "tool_end", "name": "web_search", "output": "ok"},
        {"type": "tool_error", "name": "grep_search", "error": "timeout"},
    ]
    section = d._format_tool_calls_log(log)
    assert "START web_search" in section
    assert "END web_search" in section
    assert "ERROR grep_search" in section


def test_skill_search_excludes_draft(tmp_path: Path):
    skills = tmp_path / "skills"
    skills.mkdir()
    draft = skills / "draft_skill.md"
    post = frontmatter.Post(
        content="# draft",
        **{"name": "draft_skill", "description": "draft test", "status": "draft"},
    )
    draft.write_text(frontmatter.dumps(post), encoding="utf-8")
    verified = skills / "good_skill.md"
    post2 = frontmatter.Post(
        content="# good",
        **{"name": "good_skill", "description": "good draft test", "status": "verified"},
    )
    verified.write_text(frontmatter.dumps(post2), encoding="utf-8")
    reg = SkillRegistry(curated_dir=str(skills), curated_fallback_dir=str(tmp_path / "none"))
    hits = reg.search("draft", top_k=5)
    names = [h["name"] for h in hits]
    assert "draft_skill" not in names
    assert "good_skill" in names


def test_admin_promote_skill(tmp_path: Path):
    skills = tmp_path / "skills"
    skills.mkdir()
    path = skills / "draft_one.md"
    post = frontmatter.Post(
        content="# x",
        **{"name": "draft_one", "description": "d", "status": "draft", "source": "generated"},
    )
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    reg = SkillRegistry(curated_dir=str(skills), curated_fallback_dir=str(tmp_path / "none"))
    assert reg.get_meta("draft_one")["status"] == "draft"
    loaded = frontmatter.loads(path.read_text(encoding="utf-8"))
    loaded.metadata["status"] = "verified"
    path.write_text(frontmatter.dumps(loaded), encoding="utf-8")
    reg.reload()
    assert reg.get_meta("draft_one")["status"] == "verified"
