"""Helper condivisi dai test del canale WhatsApp (DB isolato, canale, Graph finto)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "whatsapp"
TENANT = "default"
WABA_ID = "WABA1"
PNID = "1234567890"
APP_SECRET = "test-app-secret"
ACCESS_TOKEN = "EAAG-test-token-1234"
DISPLAY_PHONE = "+39 02 1234 5678"


def load_fixture(name: str) -> Dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / f"{name}.json").read_bytes()


async def setup_db(monkeypatch, tmp_path, users=(("u1", "mario"), ("u2", "giulia"))):
    """DB SQLite isolato + cache in memoria per test (niente stato condiviso)."""
    monkeypatch.setenv("AION_DB_URL", f"sqlite+aiosqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("AION_UNIFIED_DB", "1")
    monkeypatch.setenv("AION_DEFAULT_TENANT_ID", TENANT)
    monkeypatch.setenv("AION_REDIS_FALLBACK_LOCAL", "1")
    monkeypatch.setenv("AION_CHAT_URL", "https://aion.example.com")
    monkeypatch.setenv("AION_PUBLIC_API_URL", "https://aion.example.com/api")
    monkeypatch.setenv("AION_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("AION_REDIS_URL", raising=False)
    monkeypatch.delenv("AION_WHATSAPP_FORCE_DISABLE", raising=False)

    from src.channels.whatsapp import config_service, dispatcher, linking
    from src.data import engine as engine_mod
    from src.data.bootstrap import ensure_bootstrap_schema
    from src.data.engine import get_async_session_maker, init_engine
    from src.data.models import User

    monkeypatch.setattr(engine_mod, "_engine", None)
    monkeypatch.setattr(engine_mod, "_session_factory", None)
    config_service.invalidate_cache()

    cache: Dict[str, str] = {}

    async def _get(key: str) -> Optional[str]:
        return cache.get(key)

    async def _set(key: str, value: str, ttl_sec: int = 300) -> None:
        cache[key] = value

    for mod in (linking, dispatcher):
        monkeypatch.setattr(mod, "cache_get", _get)
        monkeypatch.setattr(mod, "cache_set", _set)

    eng = init_engine()
    await ensure_bootstrap_schema(eng)
    async with get_async_session_maker()() as session:
        for uid, ident in users:
            session.add(
                User(
                    id=uid,
                    tenant_id=TENANT,
                    identifier=ident,
                    display_name=ident.capitalize(),
                    roles_json="[]",
                )
            )
        await session.commit()
    return cache


@pytest.fixture
async def wa_db(monkeypatch, tmp_path):
    """``setup_db`` + chiusura dell'engine (evita thread aiosqlite orfani)."""
    cache = await setup_db(monkeypatch, tmp_path)
    yield cache
    from src.data import engine as engine_mod

    if engine_mod._engine is not None:
        await engine_mod._engine.dispose()


async def configure_channel(*, validated: bool = True, enabled: bool = True):
    from src.channels.whatsapp import config_service

    await config_service.upsert_channel(
        TENANT,
        waba_id=WABA_ID,
        phone_number_id=PNID,
        access_token=ACCESS_TOKEN,
        app_secret=APP_SECRET,
    )
    if validated:
        await config_service.mark_validated(
            TENANT, None, display_phone_number=DISPLAY_PHONE, verified_name="ACME"
        )
    if enabled:
        await config_service.set_enabled(TENANT, True)
    return await config_service.get_channel(TENANT)


def signed_headers(raw: bytes, secret: str = APP_SECRET) -> Dict[str, str]:
    from src.channels.whatsapp.signature import compute_signature

    return {
        "content-type": "application/json",
        "x-hub-signature-256": compute_signature(raw, secret),
    }


class FakeGraph:
    """Sostituisce ``GraphClient`` nel dispatcher e registra gli invii.

    Media: ``media_bytes`` is what ``download_media`` returns (or
    ``download_error`` is raised); uploads and media messages are recorded in
    ``uploads`` / ``media_sent`` (media messages also land in ``sent`` with
    ``body=None`` so the interleaving with text replies can be asserted).
    """

    def __init__(self) -> None:
        self.sent: List[Dict[str, Any]] = []
        self.typing: List[str] = []
        self.read: List[str] = []
        self.uploads: List[Dict[str, Any]] = []
        self.media_sent: List[Dict[str, Any]] = []
        self.media_bytes = b"\x89PNG fake image"
        self.download_error: Optional[Exception] = None
        self.downloaded: List[str] = []
        self._n = 0

    def factory(self, token: str, *args: Any, **kwargs: Any) -> "FakeGraph":
        return self

    async def send_text(self, phone_number_id, body, *, to=None, recipient=None, **_):
        self._n += 1
        self.sent.append({"body": body, "to": to, "recipient": recipient})
        return f"wamid.OUT{self._n}"

    async def mark_read_typing(self, phone_number_id, wamid) -> None:
        self.typing.append(wamid)

    async def mark_read(self, phone_number_id, wamid) -> None:
        self.read.append(wamid)

    async def get_media(self, media_id, *, phone_number_id=None):
        return {
            "id": media_id,
            "url": f"https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid={media_id}",
        }

    async def download_media(self, url, *, max_bytes):
        self.downloaded.append(url)
        if self.download_error is not None:
            raise self.download_error
        return self.media_bytes

    async def upload_media(self, phone_number_id, data, mime, filename):
        self.uploads.append({"data": data, "mime": mime, "filename": filename})
        return f"MEDIA-UP{len(self.uploads)}"

    async def send_media(
        self, phone_number_id, kind, media_id, *, to=None, recipient=None, **kwargs
    ):
        self._n += 1
        entry = {"kind": kind, "media_id": media_id, "to": to, **kwargs}
        self.media_sent.append(entry)
        self.sent.append({"body": None, "media": entry, "to": to})
        return f"wamid.OUT{self._n}"

    @property
    def bodies(self) -> List[str]:
        return [s["body"] for s in self.sent if s["body"] is not None]
