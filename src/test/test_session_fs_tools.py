"""Test per src/tools/session_fs_tools.py."""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

_TMP_DATA: str | None = None


def _setup_temp_session() -> tuple[str, Path]:
    sid = f"test_{uuid.uuid4().hex[:8]}"
    root = Path(_TMP_DATA) / "sessions" / sid  # type: ignore
    (root / "workspace").mkdir(parents=True, exist_ok=True)
    (root / "uploads").mkdir(parents=True, exist_ok=True)
    (root / "derived").mkdir(parents=True, exist_ok=True)
    return sid, root


class TestEditFile(unittest.TestCase):
    def setUp(self):
        global _TMP_DATA
        _TMP_DATA = tempfile.mkdtemp()
        os.environ["AION_DATA_DIR"] = _TMP_DATA
        self.sid, self.root = _setup_temp_session()
        self.ws = self.root / "workspace"

    def tearDown(self):
        if _TMP_DATA:
            shutil.rmtree(_TMP_DATA, ignore_errors=True)

    def _write(self, name: str, content: str) -> Path:
        p = self.ws / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_single_match(self):
        from src.tools.session_fs_tools import edit_file

        p = self._write("test.py", "x = 1\ny = 2\n")
        count, msg = edit_file(p, "x = 1", "x = 42")
        self.assertEqual(count, 1)
        self.assertEqual(p.read_text(), "x = 42\ny = 2\n")

    def test_zero_matches_raises(self):
        from src.tools.session_fs_tools import EditError, edit_file

        p = self._write("test.py", "x = 1\n")
        with self.assertRaises(EditError) as ctx:
            edit_file(p, "not_here", "replacement")
        self.assertEqual(ctx.exception.code, "zero_matches")

    def test_multiple_matches_raises(self):
        from src.tools.session_fs_tools import EditError, edit_file

        p = self._write("test.py", "x = 1\nx = 1\n")
        with self.assertRaises(EditError) as ctx:
            edit_file(p, "x = 1", "x = 42")
        self.assertEqual(ctx.exception.code, "multiple_matches")

    def test_replace_all(self):
        from src.tools.session_fs_tools import edit_file

        p = self._write("test.py", "x = 1\nx = 1\nx = 1\n")
        count, _ = edit_file(p, "x = 1", "x = 99", replace_all=True)
        self.assertEqual(count, 3)
        self.assertEqual(p.read_text(), "x = 99\nx = 99\nx = 99\n")

    def test_atomic_write(self):
        from src.tools.session_fs_tools import edit_file

        original = "original content\n"
        p = self._write("test.py", original)
        edit_file(p, "original", "replaced")
        self.assertEqual(p.read_text(), "replaced content\n")
        tmps = list(self.ws.glob("*.tmp"))
        self.assertEqual(len(tmps), 0)

    def test_versioning_on_edit(self):
        from src.tools.session_fs_tools import edit_file

        p = self._write("script.py", "version = 1\n")
        edit_file(p, "version = 1", "version = 2")
        versions_dir = self.ws / ".versions" / "script.py"
        self.assertTrue(versions_dir.is_dir())
        archived = list(versions_dir.glob("v*.py"))
        self.assertEqual(len(archived), 1)
        self.assertIn("version = 1", archived[0].read_text())

    def test_crlf_preserved(self):
        from src.tools.session_fs_tools import edit_file

        p = self.ws / "win.py"
        p.write_bytes(b"line1\r\nline2\r\n")
        edit_file(p, "line1", "LINE1")
        content = p.read_text(encoding="utf-8")
        self.assertIn("LINE1", content)

    def test_file_not_found(self):
        from src.tools.session_fs_tools import EditError, edit_file

        p = self.ws / "ghost.py"
        with self.assertRaises(EditError) as ctx:
            edit_file(p, "x", "y")
        self.assertEqual(ctx.exception.code, "not_found")

    def test_binary_file_rejected(self):
        from src.tools.session_fs_tools import EditError, edit_file

        p = self.ws / "data.bin"
        p.write_bytes(b"\x00\x01\x02\xff")
        with self.assertRaises(EditError) as ctx:
            edit_file(p, "x", "y")
        self.assertEqual(ctx.exception.code, "binary_file")


class TestGrepContent(unittest.TestCase):
    def setUp(self):
        global _TMP_DATA
        _TMP_DATA = tempfile.mkdtemp()
        os.environ["AION_DATA_DIR"] = _TMP_DATA
        self.sid, self.root = _setup_temp_session()
        self.ws = self.root / "workspace"

    def tearDown(self):
        if _TMP_DATA:
            shutil.rmtree(_TMP_DATA, ignore_errors=True)

    def test_basic_regex_match(self):
        from src.tools.session_fs_tools import grep_content

        (self.ws / "a.py").write_text("def foo():\n    pass\n")
        (self.ws / "b.py").write_text("def bar():\n    pass\n")
        results = grep_content(self.root, self.ws, r"def \w+")
        self.assertEqual(len(results), 2)
        names = {r["file"].split("/")[-1] for r in results}
        self.assertIn("a.py", names)
        self.assertIn("b.py", names)

    def test_fixed_string(self):
        from src.tools.session_fs_tools import grep_content

        (self.ws / "c.py").write_text("x = 1 + 2\n")
        results = grep_content(self.root, self.ws, "1 + 2", fixed_string=True)
        self.assertEqual(len(results), 1)

    def test_glob_filter(self):
        from src.tools.session_fs_tools import grep_content

        (self.ws / "x.py").write_text("hello world\n")
        (self.ws / "y.md").write_text("hello world\n")
        results = grep_content(self.root, self.ws, "hello", glob_filter="*.py")
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["file"].endswith(".py"))

    def test_truncation(self):
        from src.tools.session_fs_tools import GrepTruncated, grep_content

        for i in range(10):
            (self.ws / f"f{i}.py").write_text("match\n")
        with self.assertRaises(GrepTruncated) as ctx:
            grep_content(self.root, self.ws, "match", max_matches=5)
        self.assertEqual(len(ctx.exception.results), 5)

    def test_invalid_regex(self):
        from src.tools.session_fs_tools import grep_content

        (self.ws / "a.py").write_text("test\n")
        with self.assertRaises(re.error):
            grep_content(self.root, self.ws, "[invalid")


class TestReadFileChunk(unittest.TestCase):
    def setUp(self):
        global _TMP_DATA
        _TMP_DATA = tempfile.mkdtemp()
        os.environ["AION_DATA_DIR"] = _TMP_DATA
        self.sid, self.root = _setup_temp_session()
        self.ws = self.root / "workspace"

    def tearDown(self):
        if _TMP_DATA:
            shutil.rmtree(_TMP_DATA, ignore_errors=True)

    def test_basic_read(self):
        from src.tools.session_fs_tools import read_file_chunk

        p = self.ws / "big.txt"
        p.write_text("\n".join(f"line {i}" for i in range(1000)))
        result = read_file_chunk(p, offset_lines=0, max_lines=10)
        self.assertEqual(result["start_line"], 1)
        self.assertEqual(result["end_line"], 10)
        self.assertEqual(result["total_lines"], 1000)
        self.assertTrue(result["truncated"])

    def test_offset_read(self):
        from src.tools.session_fs_tools import read_file_chunk

        p = self.ws / "big.txt"
        lines = [f"line {i}" for i in range(100)]
        p.write_text("\n".join(lines))
        result = read_file_chunk(p, offset_lines=50, max_lines=10)
        self.assertEqual(result["start_line"], 51)
        self.assertIn("line 50", result["content"])

    def test_offset_beyond_eof(self):
        from src.tools.session_fs_tools import read_file_chunk

        p = self.ws / "small.txt"
        p.write_text("only one line\n")
        result = read_file_chunk(p, offset_lines=999, max_lines=10)
        self.assertEqual(result["content"], "")
        self.assertIn("note", result)

    def test_file_not_found(self):
        from src.tools.session_fs_tools import read_file_chunk

        p = self.ws / "ghost.txt"
        with self.assertRaises(FileNotFoundError):
            read_file_chunk(p)


class TestFnmatchGlob(unittest.TestCase):
    def setUp(self):
        global _TMP_DATA
        _TMP_DATA = tempfile.mkdtemp()
        os.environ["AION_DATA_DIR"] = _TMP_DATA
        self.sid, self.root = _setup_temp_session()
        self.ws = self.root / "workspace"

    def tearDown(self):
        if _TMP_DATA:
            shutil.rmtree(_TMP_DATA, ignore_errors=True)

    def test_basic_glob(self):
        from src.tools.session_fs_tools import fnmatch_glob

        (self.ws / "a.py").touch()
        (self.ws / "b.py").touch()
        (self.ws / "c.md").touch()
        results = fnmatch_glob(self.root, self.ws, "*.py")
        self.assertEqual(len(results), 2)

    def test_recursive_glob(self):
        from src.tools.session_fs_tools import fnmatch_glob

        sub = self.ws / "sub"
        sub.mkdir()
        (sub / "deep.py").touch()
        (self.ws / "top.py").touch()
        results = fnmatch_glob(self.root, self.ws, "**/*.py")
        self.assertEqual(len(results), 2)

    def test_max_paths_truncation(self):
        from src.tools.session_fs_tools import fnmatch_glob

        for i in range(20):
            (self.ws / f"f{i}.py").touch()
        results = fnmatch_glob(self.root, self.ws, "*.py", max_paths=5)
        self.assertLessEqual(len([r for r in results if "TRONCATO" not in r]), 5)


if __name__ == "__main__":
    unittest.main()
