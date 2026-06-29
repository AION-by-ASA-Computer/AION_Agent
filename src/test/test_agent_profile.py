"""Profile loader skips junk duplicate files."""
import textwrap
from pathlib import Path

from src.agent_profile import ProfileManager


def test_load_all_skips_copy_and_old_files(tmp_path: Path):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "good.yaml").write_text(
        textwrap.dedent(
            """
            name: Good
            description: ok
            instructions: test
            skills: []
            mcp_servers: []
            """
        ),
        encoding="utf-8",
    )
    (profiles / "generic_assistant copy.yaml").write_text(
        "name: Copy\ndescription: x\ninstructions: x\nskills: []\nmcp_servers: []\n",
        encoding="utf-8",
    )
    (profiles / "foo_OLD.yaml").write_text(
        "name: Old\ndescription: x\ninstructions: x\nskills: []\nmcp_servers: []\n",
        encoding="utf-8",
    )
    mgr = ProfileManager(profiles_dir=str(profiles))
    assert "good" in mgr._by_slug
    assert len(mgr._by_slug) == 1


def test_profile_max_agent_steps_from_yaml(tmp_path: Path):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "orch.yaml").write_text(
        textwrap.dedent(
            """
            name: Orch
            description: ok
            instructions: test
            skills: []
            mcp_servers: []
            agent:
              max_steps: 8
            """
        ),
        encoding="utf-8",
    )
    mgr = ProfileManager(profiles_dir=str(profiles))
    p = mgr.get_profile("orch")
    assert p is not None
    assert p.max_agent_steps == 8
