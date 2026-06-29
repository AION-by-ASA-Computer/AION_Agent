from src.runtime.turn_answer_fallback import build_tool_result_fallback


def test_fallback_from_ndjson_sql():
    steps = [
        {
            "name": "execute_sql",
            "output": '{"device_id":1}\n{"device_id":2}\n',
            "is_error": False,
        }
    ]
    text = build_tool_result_fallback(steps)
    assert "device_id" in text
    assert "fallback" in text.lower()
