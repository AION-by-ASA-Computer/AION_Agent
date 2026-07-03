from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx


class AionClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-Api-Key": api_key}

    async def create_conversation(
        self, profile: str, user_id: str, **extra: Any
    ) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.post(
                f"{self.base_url}/v1/conversations",
                headers=self.headers,
                json={"profile": profile, "user_id": user_id, **extra},
            )
            r.raise_for_status()
            return r.json()

    async def chat_stream(
        self,
        conversation_id: str,
        message: str,
        profile: str = "aion_std",
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=None) as c:
            payload = {
                "conversation_id": conversation_id,
                "message": message,
                "profile": profile,
            }
            if attachments:
                payload["attachments"] = attachments

            async with c.stream(
                "POST",
                f"{self.base_url}/v1/chat/stream",
                headers=self.headers,
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("data:"):
                        yield json.loads(line[5:].strip())

    async def list_conversations(
        self, user_id: Optional[str] = None, limit: int = 20
    ) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as c:
            params = {"limit": limit}
            if user_id:
                params["user_id"] = user_id
            r = await c.get(
                f"{self.base_url}/v1/conversations", headers=self.headers, params=params
            )
            r.raise_for_status()
            return r.json()

    async def get_conversation(self, conversation_id: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.get(
                f"{self.base_url}/v1/conversations/{conversation_id}",
                headers=self.headers,
            )
            r.raise_for_status()
            return r.json()

    async def delete_conversation(self, conversation_id: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.delete(
                f"{self.base_url}/v1/conversations/{conversation_id}",
                headers=self.headers,
            )
            r.raise_for_status()
            return r.json()

    async def get_messages(
        self, conversation_id: str, limit: int = 50
    ) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.get(
                f"{self.base_url}/v1/conversations/{conversation_id}/messages",
                headers=self.headers,
                params={"limit": limit},
            )
            r.raise_for_status()
            return r.json()

    async def upload_files(
        self, session_id: str, files: List[tuple[str, bytes, Optional[str]]]
    ) -> Dict[str, Any]:
        """
        Carica uno o più file nella sessione.
        files: lista di (nome_file, contenuto_bytes, mime_type_opzionale)
        """
        async with httpx.AsyncClient(timeout=60.0) as c:
            upload_data = [
                ("files", (name, content, mime or "application/octet-stream"))
                for name, content, mime in files
            ]
            r = await c.post(
                f"{self.base_url}/sessions/{session_id}/upload",
                headers=self.headers,
                files=upload_data,
            )
            r.raise_for_status()
            return r.json()

    async def list_files(
        self, session_id: str, subdir: str = "uploads"
    ) -> Dict[str, Any]:
        """Elenco file nella sessione."""
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.get(
                f"{self.base_url}/sessions/{session_id}/files",
                headers=self.headers,
                params={"subdir": subdir},
            )
            r.raise_for_status()
            return r.json()

    async def download_file(self, session_id: str, relative_path: str) -> bytes:
        """Scarica un file dalla sessione."""
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.get(
                f"{self.base_url}/sessions/{session_id}/download",
                headers=self.headers,
                params={"relative_path": relative_path},
            )
            r.raise_for_status()
            return r.content
