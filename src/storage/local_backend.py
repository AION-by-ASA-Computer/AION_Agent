from __future__ import annotations

import shutil
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Literal, Optional, Union

from .backend import StorageBackend, StorageObject, StorageObjectMeta


class LocalBackend(StorageBackend):
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _safe(self, key: str) -> Path:
        rel = key.lstrip("/").replace("..", "_")
        p = (self.root / rel).resolve()
        try:
            p.relative_to(self.root)
        except ValueError as e:
            raise ValueError("Invalid storage key path") from e
        return p

    def put_object(
        self,
        key: str,
        data: Union[bytes, BinaryIO],
        content_type: str,
    ) -> StorageObject:
        p = self._safe(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        body = data.read() if hasattr(data, "read") else data  # type: ignore[union-attr]
        if not isinstance(body, bytes):
            body = bytes(body)
        p.write_bytes(body)
        return StorageObject(key=key, size_bytes=len(body), content_type=content_type)

    def get_object(self, key: str) -> bytes:
        return self._safe(key).read_bytes()

    def get_object_stream(self, key: str) -> BinaryIO:
        return BytesIO(self.get_object(key))

    def head_object(self, key: str) -> Optional[StorageObjectMeta]:
        p = self._safe(key)
        if not p.is_file():
            return None
        st = p.stat()
        return StorageObjectMeta(
            key=key,
            size_bytes=int(st.st_size),
            content_type="application/octet-stream",
        )

    def list_prefix(self, prefix: str, limit: int = 1000) -> list[StorageObjectMeta]:
        base = self._safe(prefix.rstrip("/") + "/placeholder").parent
        if prefix.strip("/"):
            base = self._safe(prefix.rstrip("/"))
        if not base.exists():
            return []
        out: list[StorageObjectMeta] = []
        pattern = prefix.lstrip("/")
        for fp in base.rglob("*"):
            if len(out) >= limit:
                break
            if not fp.is_file():
                continue
            rel = fp.relative_to(self.root).as_posix()
            if pattern and not rel.startswith(pattern):
                continue
            st = fp.stat()
            out.append(
                StorageObjectMeta(
                    key=rel,
                    size_bytes=int(st.st_size),
                    content_type="application/octet-stream",
                )
            )
        return out

    def delete_object(self, key: str) -> bool:
        p = self._safe(key)
        if p.is_file():
            p.unlink()
            return True
        return False

    def delete_prefix(self, prefix: str) -> int:
        base = self._safe(prefix.rstrip("/") + "/x").parent
        if not base.exists() or base == self.root and not prefix.strip("/"):
            return 0
        n = 0
        for fp in list(base.rglob("*")):
            if fp.is_file():
                fp.unlink()
                n += 1
        try:
            if base != self.root and base.is_dir():
                shutil.rmtree(base, ignore_errors=True)
        except Exception:
            pass
        return n

    def generate_presigned_url(
        self,
        key: str,
        method: Literal["GET", "PUT"],
        expires_in: int,
    ) -> str:
        return f"local://{self.root.as_posix()}/{key.lstrip('/')}?expires={expires_in}&method={method}"
