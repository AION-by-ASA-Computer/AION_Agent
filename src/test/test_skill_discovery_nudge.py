from src.runtime.skill_discovery_nudge import (
    build_plan_mode_skill_hint,
    build_skill_discovery_nudge,
    should_inject_skill_discovery_nudge,
)
from src.skill_registry import SkillRegistry


def test_should_inject_for_docx_request():
    assert should_inject_skill_discovery_nudge(
        "Crea un documento Word docx completo",
        profile_has_skills_hub=True,
    )


def test_should_not_inject_without_hub():
    assert not should_inject_skill_discovery_nudge(
        "Crea un documento Word docx",
        profile_has_skills_hub=False,
    )


def test_should_not_inject_in_plan_mode():
    assert not should_inject_skill_discovery_nudge(
        "Crea un documento Word docx",
        profile_has_skills_hub=True,
        agent_mode="plan",
    )


def test_build_nudge_mentions_docx():
    text = build_skill_discovery_nudge("corso ML in docx")
    assert "skill_search" in text
    assert "docx" in text


def test_plan_mode_hint_defers_skill_view_and_web_search():
    text = build_plan_mode_skill_hint("corso ML completo in Word con citazioni")
    assert "<plan>" in text
    assert "Do not" in text and "skill_view" in text
    assert "web_search" in text
    assert "Approve Plan" in text or "after" in text


def test_skill_search_respects_allowed_names(tmp_path, monkeypatch):
    reg = SkillRegistry(
        curated_dir=str(tmp_path / "empty"),
        curated_fallback_dir=str(tmp_path / "skills"),
    )
    d = tmp_path / "skills"
    d.mkdir(parents=True)
    (d / "alpha.md").write_text(
        "---\nname: alpha\ndescription: alpha skill\ntags: []\n---\nbody",
        encoding="utf-8",
    )
    (d / "beta.md").write_text(
        "---\nname: beta\ndescription: beta skill\ntags: []\n---\nbody",
        encoding="utf-8",
    )
    reg.reload()
    hits = reg.search("alpha", top_k=5, allowed_names=["alpha"])
    assert len(hits) == 1
    assert hits[0]["name"] == "alpha"
    none = reg.search("beta", top_k=5, allowed_names=["alpha"])
    assert none == []
