from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from io import BytesIO
from typing import BinaryIO, Literal, Optional, Union


@dataclass
class StorageObject:
    key: str
    size_bytes: int
    content_type: str


@dataclass
class StorageObjectMeta:
    key: str
    size_bytes: int
    content_type: str


class StorageBackend(ABC):
    @abstractmethod
    def put_object(
        self,
        key: str,
        data: Union[bytes, BinaryIO],
        content_type: str,
    ) -> StorageObject:
        ...

    @abstractmethod
    def get_object(self, key: str) -> bytes:
        ...

    @abstractmethod
    def get_object_stream(self, key: str) -> BinaryIO:
        ...

    @abstractmethod
    def head_object(self, key: str) -> Optional[StorageObjectMeta]:
        ...

    @abstractmethod
    def list_prefix(self, prefix: str, limit: int = 1000) -> list[StorageObjectMeta]:
        ...

    @abstractmethod
    def delete_object(self, key: str) -> bool:
        ...

    @abstractmethod
    def delete_prefix(self, prefix: str) -> int:
        ...

    @abstractmethod
    def generate_presigned_url(
        self,
        key: str,
        method: Literal["GET", "PUT"],
        expires_in: int,
    ) -> str:
        ...

    def put_bytes(self, key: str, data: bytes, content_type: str) -> StorageObject:
        return self.put_object(key, data, content_type)
