import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.mcp_manager import MCPManager


class TestResolveStdioScriptPath(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.mcp_dir = self.root / "mcp_servers" / "demo"
        self.mcp_dir.mkdir(parents=True)
        self.script = self.mcp_dir / "server.py"
        self.script.write_text("# demo\n", encoding="utf-8")
        self.patch_repo_root = patch(
            "src.mcp_manager._repo_root", return_value=self.root
        )
        self.patch_repo_root.start()

    def tearDown(self):
        self.patch_repo_root.stop()
        self.temp_dir.cleanup()

    def test_resolves_relative_path_under_mcp_servers(self):
        resolved = MCPManager.resolve_stdio_script_path("demo/server.py")
        self.assertEqual(resolved, str(self.script.resolve()))

    def test_resolves_path_prefixed_with_mcp_servers(self):
        resolved = MCPManager.resolve_stdio_script_path("mcp_servers/demo/server.py")
        self.assertEqual(resolved, str(self.script.resolve()))

    def test_resolves_absolute_path_under_repo(self):
        resolved = MCPManager.resolve_stdio_script_path(str(self.script))
        self.assertEqual(resolved, str(self.script.resolve()))

    def test_rejects_path_traversal(self):
        outside = self.root.parent / "outside.py"
        outside.write_text("# outside\n", encoding="utf-8")
        self.assertIsNone(MCPManager.resolve_stdio_script_path("../outside.py"))
        self.assertIsNone(MCPManager.resolve_stdio_script_path(str(outside)))

    def test_rejects_non_python_and_flags(self):
        self.assertIsNone(MCPManager.resolve_stdio_script_path("--help"))
        self.assertIsNone(MCPManager.resolve_stdio_script_path("demo/server.txt"))


if __name__ == "__main__":
    unittest.main()
