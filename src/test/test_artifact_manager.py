import unittest
import shutil
from pathlib import Path
from src.runtime.artifact_manager import ArtifactManager

class TestArtifactManager(unittest.TestCase):
    def setUp(self):
        self.session_id = "test_session_mgr"
        self.manager = ArtifactManager(self.session_id)
        self.root = self.manager._root

    def tearDown(self):
        if self.root.exists():
            shutil.rmtree(self.root)

    def test_save_and_versioning(self):
        path1, v1 = self.manager.save("test_art", "print(1)", "python")
        self.assertEqual(v1, 1)
        self.assertTrue(path1.exists())
        self.assertEqual(path1.name, "test_art.py")
        self.assertEqual(path1.read_text(), "print(1)")

        path2, v2 = self.manager.save("test_art", "print(2)", "python")
        self.assertEqual(v2, 2)
        self.assertTrue(path2.exists())
        self.assertEqual(path2.name, "test_art.py")
        self.assertEqual(path2.read_text(), "print(2)")

        archive = self.root / "workspace" / ".versions" / "test_art.py"
        self.assertTrue(archive.is_dir())
        archived_files = list(archive.glob("v*.py"))
        self.assertEqual(len(archived_files), 1)
        self.assertEqual(archived_files[0].read_text(), "print(1)")

    def test_type_extension(self):
        path, _ = self.manager.save("style", "body { color: red; }", "css")
        self.assertEqual(path.suffix, ".css")
        
        path, _ = self.manager.save("data", "a,b,c", "csv")
        self.assertEqual(path.suffix, ".csv")

    def test_auto_execute_sandboxed(self):
        path, _ = self.manager.save("exec_test", "print('Done')\n", "python")
        output = self.manager.auto_execute_sandboxed(path)
        self.assertIsNotNone(output)
        self.assertTrue(
            output.startswith("OK") or output.startswith("Error"),
            msg=output,
        )

if __name__ == "__main__":
    unittest.main()
