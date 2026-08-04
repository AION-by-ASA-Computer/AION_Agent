from src.benchmarks.env_config import (
    apply_mnemos_env,
    resolve_judge_profile,
    resolve_project_slug,
)


def test_resolve_project_slug_per_run():
    assert resolve_project_slug("bench_abc123", {}) == "lme_bench_abc123"
    assert resolve_project_slug("bench_abc123", {"project_slug": "custom"}) == "custom"


def test_resolve_judge_profile(monkeypatch):
    # A developer .env may define this; the fallback only applies when it is unset.
    monkeypatch.delenv("AION_LME_V2_JUDGE_PROFILE", raising=False)
    assert resolve_judge_profile("generic_assistant", {}) == "generic_assistant"
    assert (
        resolve_judge_profile("generic_assistant", {"judge_profile": "aion_std"})
        == "aion_std"
    )


def test_resolve_judge_profile_env_overrides_run_profile(monkeypatch):
    monkeypatch.setenv("AION_LME_V2_JUDGE_PROFILE", "aion_std")
    assert resolve_judge_profile("generic_assistant", {}) == "aion_std"
    assert (
        resolve_judge_profile("generic_assistant", {"judge_profile": "custom"})
        == "custom"
    )


def test_apply_mnemos_env():
    applied = apply_mnemos_env(
        {
            "mnemos": {
                "AION_MNEMOS_RECALL_LIMIT": "25",
                "max_questions": 3,
            }
        }
    )
    assert applied == {"AION_MNEMOS_RECALL_LIMIT": "25"}
