import tempfile
from pathlib import Path

from src.storage.local_backend import LocalBackend


def test_local_backend_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        b = LocalBackend(Path(d))
        key = "default/conversations/c1/uploads/f1.txt"
        b.put_bytes(key, b"hello", "text/plain")
        assert b.get_object(key) == b"hello"
        meta = b.head_object(key)
        assert meta is not None
        assert meta.size_bytes == 5
