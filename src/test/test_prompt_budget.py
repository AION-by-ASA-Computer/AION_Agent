from src.runtime.prompt_budget import PromptBudget, apply_injection_budget


def test_prompt_budget_drops_low_priority_layers(monkeypatch):
    monkeypatch.setenv("AION_PROMPT_LAYER_TOTAL_BUDGET", "500")
    budget = PromptBudget()
    budget.add_layer("ltm", "x" * 2000, priority=10)
    budget.add_layer("plan_reminder", "short", priority=90)
    out = budget.build()
    assert "plan_reminder" in budget.dropped
    assert len(out) > 100


def test_apply_injection_budget_preserves_core(monkeypatch):
    monkeypatch.setenv("AION_PROMPT_LAYER_TOTAL_BUDGET", "200")
    core = "User question here"
    layers = [
        {"key": "exploration_reminder", "text": "x" * 800},
        {"key": "sql_query_memory", "text": "schema hint"},
    ]
    out = apply_injection_budget(core, layers)
    assert core in out
    assert "schema hint" in out or "User question" in out
