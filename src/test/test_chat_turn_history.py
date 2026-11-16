from src.chat_turn_history import collapse_redundant_assistant_fragments
from src.data.message_roles import normalize_message_role


def test_collapse_keeps_richest_assistant_per_turn():
    class Row:
        def __init__(
            self,
            id,
            role,
            content="",
            reasoning="",
            metadata_json=None,
            timeline_json=None,
        ):
            self.id = id
            self.role = role
            self.content = content
            self.reasoning = reasoning
            self.metadata_json = metadata_json
            self.timeline_json = timeline_json

    messages = [
        Row("u1", "user", "Q"),
        Row("a1", "assistant", "Full answer with tools.", reasoning="think"),
        Row("frag1", "assistant", "Partial snippet."),
        Row("frag2", "assistant", "\n\n"),
        Row("u2", "user", "Q2"),
        Row("a2", "assistant", "Second answer."),
    ]
    steps_by_msg = {"a1": [{"id": "s1"}]}
    atts_by_msg = {}

    collapsed = collapse_redundant_assistant_fragments(
        messages, steps_by_msg=steps_by_msg, atts_by_msg=atts_by_msg
    )
    assistant_ids = [
        r.id for r in collapsed if normalize_message_role(r.role) == "assistant"
    ]
    assert assistant_ids == ["a1", "a2"]


def test_collapse_keeps_memorization_assistant():
    class Row:
        def __init__(self, id, role, content="", metadata_json=None):
            self.id = id
            self.role = role
            self.content = content
            self.reasoning = ""
            self.metadata_json = metadata_json
            self.timeline_json = None

    messages = [
        Row("u1", "user", "Hi"),
        Row("a1", "assistant", "Hello!"),
        Row(
            "memo",
            "assistant",
            "L'agente ha memorizzato: foo",
            metadata_json='{"memorized_message_id": "a1"}',
        ),
    ]
    collapsed = collapse_redundant_assistant_fragments(
        messages, steps_by_msg={}, atts_by_msg={}
    )
    assistant_ids = [
        r.id for r in collapsed if normalize_message_role(r.role) == "assistant"
    ]
    assert assistant_ids == ["a1", "memo"]


def test_collapse_keeps_every_plan_execution_turn():
    """Plan run: each internal trigger is its own turn, so every task reply and
    the final plan-closing message survive (they used to collapse into one)."""

    class Row:
        def __init__(self, id, role, content="", metadata_json=None):
            self.id = id
            self.role = role
            self.content = content
            self.reasoning = ""
            self.metadata_json = metadata_json
            self.timeline_json = None

    plan = '{"plan_id": "execution_plan_x", "plan_task_id": %s}'
    messages = [
        Row("u1", "user", "Write an article, make a plan"),
        Row("a-plan", "assistant", "Plan registered."),
        Row("i1", "internal", "Execute plan task `task_01`", plan % '"task_01"'),
        Row("a1", "assistant", "Research done.", plan % '"task_01"'),
        Row("i2", "internal", "Execute plan task `task_02`", plan % '"task_02"'),
        Row("a2", "assistant", "Docx written.", plan % '"task_02"'),
        Row(
            "i-close", "internal", "All tasks completed. Close the plan", plan % "null"
        ),
        Row("a-close", "assistant", "Final summary.", plan % "null"),
    ]
    # The richest row (most steps) used to be the only survivor.
    steps_by_msg = {"a1": [{"id": "s1"}, {"id": "s2"}]}
    collapsed = collapse_redundant_assistant_fragments(
        messages, steps_by_msg=steps_by_msg, atts_by_msg={}
    )
    assistant_ids = [
        r.id for r in collapsed if normalize_message_role(r.role) == "assistant"
    ]
    assert assistant_ids == ["a-plan", "a1", "a2", "a-close"]


def test_collapse_unknown_role_does_not_split_turn():
    """Only the literal ``internal`` role opens a turn: rows with an empty role
    (normalized to "internal" elsewhere) still collapse with their turn."""

    class Row:
        def __init__(self, id, role, content=""):
            self.id = id
            self.role = role
            self.content = content
            self.reasoning = ""
            self.metadata_json = None
            self.timeline_json = None

    messages = [
        Row("u1", "user", "Q"),
        Row("a1", "assistant", "Full answer."),
        Row("x", "", "stray row"),
        Row("frag", "assistant", "dup"),
    ]
    collapsed = collapse_redundant_assistant_fragments(
        messages, steps_by_msg={"a1": [{"id": "s"}]}, atts_by_msg={}
    )
    assert [r.id for r in collapsed if r.role == "assistant"] == ["a1"]
