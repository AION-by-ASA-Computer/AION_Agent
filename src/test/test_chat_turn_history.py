from src.chat_turn_history import collapse_redundant_assistant_fragments
from src.data.message_roles import normalize_message_role


def test_collapse_keeps_richest_assistant_per_turn():
  class Row:
    def __init__(self, id, role, content="", reasoning="", metadata_json=None, timeline_json=None):
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
