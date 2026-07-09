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


def test_build_nudge_mentions_skill_view():
    text = build_skill_discovery_nudge("corso ML in docx")
    assert "skill_view" in text
    assert "aion_artifact" in text
    assert "chat reply" in text


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


def test_build_nudge_with_session_loaded_skills(tmp_path, monkeypatch):
    # Mock session_root to return our tmp_path
    monkeypatch.setattr("src.session_workspace.session_root", lambda sid: tmp_path)

    # Create the assets dir and marker files
    assets_dir = tmp_path / ".aion_skill_assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / "plane.json").write_text('{"slug": "plane"}', encoding="utf-8")
    (assets_dir / "docx.json").write_text('{"slug": "docx"}', encoding="utf-8")

    text = build_skill_discovery_nudge("corso ML in docx", session_id="test_session")
    assert "do not call" in text and "again" in text


def test_should_inject_nudge_with_loaded_skills(tmp_path, monkeypatch):
    monkeypatch.setattr("src.session_workspace.session_root", lambda sid: tmp_path)

    # Create marker files for loaded skills
    assets_dir = tmp_path / ".aion_skill_assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / "plane.json").write_text('{"slug": "plane"}', encoding="utf-8")

    # The nudge should always be injected when the skills hub is enabled
    assert should_inject_skill_discovery_nudge(
        "quali sono i progetti?",
        profile_has_skills_hub=True,
        session_id="test_session",
    )

    assert should_inject_skill_discovery_nudge(
        "crea un file word docx",
        profile_has_skills_hub=True,
        session_id="test_session",
    )

    assert should_inject_skill_discovery_nudge(
        "crea un report in docx e caricalo su plane",
        profile_has_skills_hub=True,
        session_id="test_session",
    )
