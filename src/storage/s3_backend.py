from __future__ import annotations

from io import BytesIO
from typing import BinaryIO, Literal, Optional, Union

from .backend import StorageBackend, StorageObject, StorageObjectMeta


class S3Backend(StorageBackend):
    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None,
        region: str,
        access_key: str,
        secret_key: str,
        use_path_style: bool,
        presigned_expires_default: int = 3600,
    ):
        import boto3  # type: ignore

        self._bucket = bucket
        self._pres_default = presigned_expires_default
        from botocore.config import Config

        session = boto3.session.Session(
            aws_access_key_id=access_key or None,
            aws_secret_access_key=secret_key or None,
            region_name=region or None,
        )
        self._client = session.client(
            "s3",
            endpoint_url=endpoint_url or None,
            config=Config(
                s3={"addressing_style": "path" if use_path_style else "auto"}
            ),
        )

    def put_object(
        self,
        key: str,
        data: Union[bytes, BinaryIO],
        content_type: str,
    ) -> StorageObject:
        body = data.read() if hasattr(data, "read") else data  # type: ignore[union-attr]
        if not isinstance(body, bytes):
            body = bytes(body)
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )
        return StorageObject(key=key, size_bytes=len(body), content_type=content_type)

    def get_object(self, key: str) -> bytes:
        r = self._client.get_object(Bucket=self._bucket, Key=key)
        return r["Body"].read()

    def get_object_stream(self, key: str) -> BinaryIO:
        return BytesIO(self.get_object(key))

    def head_object(self, key: str) -> Optional[StorageObjectMeta]:
        try:
            r = self._client.head_object(Bucket=self._bucket, Key=key)
        except Exception:
            return None
        ct = r.get("ContentType") or "application/octet-stream"
        ln = int(r.get("ContentLength") or 0)
        return StorageObjectMeta(key=key, size_bytes=ln, content_type=str(ct))

    def list_prefix(self, prefix: str, limit: int = 1000) -> list[StorageObjectMeta]:
        out: list[StorageObjectMeta] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(
            Bucket=self._bucket, Prefix=prefix, PaginationConfig={"MaxItems": limit}
        ):
            for obj in page.get("Contents") or []:
                k = obj.get("Key")
                if not k:
                    continue
                out.append(
                    StorageObjectMeta(
                        key=str(k),
                        size_bytes=int(obj.get("Size") or 0),
                        content_type="application/octet-stream",
                    )
                )
                if len(out) >= limit:
                    return out
        return out

    def delete_object(self, key: str) -> bool:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
            return True
        except Exception:
            return False

    def delete_prefix(self, prefix: str) -> int:
        n = 0
        for meta in self.list_prefix(prefix, limit=10000):
            if self.delete_object(meta.key):
                n += 1
        return n

    def generate_presigned_url(
        self,
        key: str,
        method: Literal["GET", "PUT"],
        expires_in: int,
    ) -> str:
        client_method = "get_object" if method == "GET" else "put_object"
        return self._client.generate_presigned_url(
            ClientMethod=client_method,
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in or self._pres_default,
        )
