from src.agent_pipeline import _is_plan_artifact_payload
from src.runtime.artifact_coercion import salvage_artifact_from_response


def test_salvage_malformed_wwdc_fence_without_hash_metadata():
    body = (
        "artifact_id: wwdc-2026-complete-guide\n"
        "title: Apple WWDC 2026\n"
        "filename: wwdc-2026-guide.md\n"
        "# Apple WWDC 2026\n\n"
        + "Annunci principali.\n" * 40
    )
    raw = f"Intro\n```markdown\n{body}```\nTail"
    salvaged = salvage_artifact_from_response(raw)
    assert salvaged is not None
    assert salvaged.artifact_id == "wwdc_2026_complete_guide"
    assert salvaged.filename == "wwdc-2026-guide.md"
    assert "Annunci principali" in salvaged.content
    assert not _is_plan_artifact_payload(
        salvaged.artifact_id, salvaged.artifact_type, salvaged.content
    )


def test_execution_plan_markdown_not_classified_as_plan_artifact():
    content = "# Execution Plan\n\n## Goal\nDoc\n\n## Tasks\n- [ ] step\n"
    assert not _is_plan_artifact_payload("wwdc_guide", "markdown", content)
