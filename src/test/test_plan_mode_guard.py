from src.runtime.plan_mode_guard import plan_mode_response_valid


def test_plan_registered_skips_tag_requirement():
    ok, reason = plan_mode_response_valid(
        "solo ricerca web, nessun tag", plan_registered=True
    )
    assert ok
    assert reason == "ok_plan_registered"


def test_valid_plan_only():
    md = """<plan title="Corso ML">
## Goal
Scrivere corso ML completo in docx con citazioni.

## Context
Ricerche web già fatte. Dopo approvazione: skill_view docx.

## Tasks
- [ ] `task_01` **skill_view docx** (profile: -) (deps: none)

## Notes
</plan>"""
    ok, reason = plan_mode_response_valid(md)
    assert ok, reason


def test_rejects_docx_script_without_plan():
    body = "Piano Corso ML\n```python\nfrom docx import Document\n```"
    ok, reason = plan_mode_response_valid(body)
    assert not ok
    assert reason == "deliverable_code_without_plan_tag"


def test_rejects_forecasting_template_inside_plan():
    body = """<plan>
## Goal
x
## Tasks
- [ ] `t1` **A** (profile: -) (deps: none)
Progetto di Forecasting con NeuralForecast
</plan>"""
    ok, reason = plan_mode_response_valid(body)
    assert not ok
    assert reason == "deliverable_or_wrong_template_in_body"
