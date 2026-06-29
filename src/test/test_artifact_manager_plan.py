import uuid

from src.runtime.artifact_manager import ARTIFACT_TYPE_MAP, ArtifactManager


def test_plan_type_maps_to_markdown_extension():
    assert ARTIFACT_TYPE_MAP.get("plan") == ".md"


def test_plan_artifact_is_saved_as_markdown_file():
    session_id = f"test_plan_{uuid.uuid4().hex[:8]}"
    manager = ArtifactManager(session_id)
    path, version = manager.save("execution_plan_case", "# Plan\n\n## Tasks\n", "plan")
    assert version == 1
    assert path.suffix == ".md"
    assert path.name == "execution_plan_case.md"
