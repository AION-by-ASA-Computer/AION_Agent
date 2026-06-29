from __future__ import annotations

import os
from functools import lru_cache

from .backend import StorageBackend
from .local_backend import LocalBackend
from .s3_backend import S3Backend


@lru_cache(maxsize=1)
def get_storage_backend() -> StorageBackend:
    kind = (os.getenv("AION_STORAGE_BACKEND") or "local").strip().lower()
    if kind == "s3":
        return S3Backend(
            bucket=os.getenv("AION_STORAGE_S3_BUCKET", "aion-sessions"),
            endpoint_url=(os.getenv("AION_STORAGE_S3_ENDPOINT_URL") or "").strip() or None,
            region=os.getenv("AION_STORAGE_S3_REGION", "us-east-1"),
            access_key=os.getenv("AION_STORAGE_S3_ACCESS_KEY", ""),
            secret_key=os.getenv("AION_STORAGE_S3_SECRET_KEY", ""),
            use_path_style=os.getenv("AION_STORAGE_S3_USE_PATH_STYLE", "0").lower()
            in ("1", "true", "yes"),
            presigned_expires_default=int(os.getenv("AION_STORAGE_S3_PRESIGNED_EXPIRES", "3600")),
        )
    root = os.getenv("AION_STORAGE_LOCAL_ROOT", "data")
    return LocalBackend(root)
