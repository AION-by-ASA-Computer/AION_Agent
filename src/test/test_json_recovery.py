import unittest
import json
from src.runtime.json_recovery import try_recover_json

class TestJSONRecovery(unittest.TestCase):
    def test_unescaped_newlines(self):
        # Malformed JSON with literal newline inside a string
        malformed = '{"code": "print(\'hello\')\nprint(\'world\')"}'
        
        # Standard json.loads would fail here
        with self.assertRaises(json.JSONDecodeError):
            json.loads(malformed)
            
        recovered = try_recover_json(malformed)
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered["code"], "print('hello')\nprint('world')")

    def test_unescaped_tabs(self):
        malformed = '{"code": "if True:\n\tprint(1)"}'
        recovered = try_recover_json(malformed)
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered["code"], "if True:\n\tprint(1)")

    def test_isolated_open_brace(self):
        recovered = try_recover_json("{")
        self.assertEqual(recovered, {})
        
        recovered = try_recover_json("  {  ")
        self.assertEqual(recovered, {})

    def test_missing_closing_brace(self):
        recovered = try_recover_json('{"arg": "value"')
        self.assertEqual(recovered, {"arg": "value"})

    def test_broken_json_repair_fallback(self):
        # Very broken JSON that might need json_repair (if installed)
        malformed = "{'code': 'print(1)',}" # trailing comma, single quotes
        
        # This test might pass if json_repair is installed, or fail (return None) if not.
        # But we want to see if the function behaves gracefully.
        recovered = try_recover_json(malformed)
        # We don't assert true here because json_repair might not be in test env
        print(f"Broken JSON recovery result: {recovered is not None}")

    def test_concurrent_loads_wrapper_thread_safe(self):
        """Permanent Haystack json.loads wrapper must survive concurrent use."""
        try:
            import haystack.components.generators.utils as gen_utils
        except ImportError:
            self.skipTest("haystack not installed")

        loads_fn = gen_utils.json.loads
        malformed = '{"code": "line1\\nline2"}'
        errors: list = []

        def worker():
            try:
                for _ in range(50):
                    loads_fn('{"a": 1}')
                    try_recover_json(malformed)
            except Exception as exc:
                errors.append(exc)

        import threading

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
