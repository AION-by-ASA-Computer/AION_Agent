from __future__ import annotations
import os
import logging
import json
import requests
import numpy as np
import asyncio
from typing import List, Tuple, Optional, Dict, Any
from datetime import datetime

from sqlalchemy import select, update, delete, func
from .data.engine import get_async_session_maker
from .data.models import CachedQuery

# Configure logging
logger = logging.getLogger("aion.query_memory")

EMBEDDINGS_PROVIDER = (os.getenv("AION_EMBEDDINGS_PROVIDER") or "openai").strip().lower()
EMBEDDING_MODEL = (os.getenv("AION_EMBEDDING_MODEL") or "").strip()
EMBEDDING_URL = (os.getenv("AION_EMBEDDING_URL") or "").strip()
EMBEDDING_REQUEST_TIMEOUT = float(os.getenv("AION_EMBEDDING_REQUEST_TIMEOUT", "5"))
EMBEDDING_API_KEY = (os.getenv("AION_EMBEDDINGS_API_KEY") or "").strip()
AUTO_VERIFY_THRESHOLD = int(os.getenv("AION_AUTO_VERIFY_THRESHOLD", "3"))

class QueryMemory:
    """Unified Query Memory using SQLAlchemy/aion.db"""
    
    def __init__(self):
        self.session_maker = get_async_session_maker()

    def get_embedding(self, text: str) -> Optional[np.ndarray]:
        """Fetch embedding from remote VLLM or Google endpoint."""
        try:
            if not EMBEDDING_MODEL:
                raise ValueError("AION_EMBEDDING_MODEL is not configured")
            if not EMBEDDING_URL:
                raise ValueError("AION_EMBEDDING_URL is not configured")

            headers = {}
            url = EMBEDDING_URL
            
            if EMBEDDINGS_PROVIDER in ("google", "gemini"):
                if EMBEDDING_API_KEY:
                    url = f"{url}"
                    headers["x-goog-api-key"] = f"{EMBEDDING_API_KEY}"
                    
                payload = {
                    "model": EMBEDDING_MODEL,
                    "content": {
                        "parts": [{"text": text}]
                    },
                    "taskType": "SEMANTIC_SIMILARITY"
                }
            else:
                if EMBEDDING_API_KEY:
                    headers["Authorization"] = f"Bearer {EMBEDDING_API_KEY}"
                payload = {"input": text, "model": EMBEDDING_MODEL}


            logger.info("URLLL %s", url)
            logger.info("PAYLOAD %s", payload)
            logger.info("HEADERS %s", headers)
            logger.info("TIMEOUT %s", EMBEDDING_REQUEST_TIMEOUT)


            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=EMBEDDING_REQUEST_TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
            
            if EMBEDDINGS_PROVIDER in ("google", "gemini"):
                # print("DATA GOT")
                # print(data)
                embedding_list = data["embedding"]["values"]
            else:
                embedding_list = data["data"][0]["embedding"]

            # print("EMBEDDINGS LISTTT")
            # print(embedding_list)
            logger.info("EMBEDDING LIST %s", embedding_list[:3])
                
            return np.array(embedding_list, dtype=np.float32)
        except Exception as e:
            logger.warning(f"Failed to fetch embedding for text: {e}")
            return None

    async def search(self, request_text: str, limit: int = 3, namespace: str = "default", verified_only: bool = False) -> List[Dict[str, Any]]:
        """Combined search: Exact -> Semantic -> Keyword."""
        async with self.session_maker() as session:
            # 1. Exact match
            q = select(CachedQuery).where(
                CachedQuery.user_request == request_text.strip(),
                CachedQuery.namespace == namespace
            )
            row = (await session.execute(q)).scalars().first()
            if row:
                return [{
                    "id": row.id, "user_request": row.user_request, "promql_query": row.promql_query,
                    "is_verified": bool(row.is_verified), "success_count": row.success_count, "score": 1.0
                }]

            # 2. Semantic search
            query_embedding = self.get_embedding(request_text)
            if query_embedding is not None:
                q = select(CachedQuery).where(CachedQuery.namespace == namespace, CachedQuery.embedding != None)
                if verified_only:
                    q = q.where(CachedQuery.is_verified == 1)
                
                candidates = (await session.execute(q)).scalars().all()
                results = []
                for cand in candidates:
                    cemb = np.frombuffer(cand.embedding, dtype=np.float32)
                    score = np.dot(query_embedding, cemb) / (np.linalg.norm(query_embedding) * np.linalg.norm(cemb))
                    if score > 0.7:
                        results.append({
                            "id": cand.id, "user_request": cand.user_request, "promql_query": cand.promql_query,
                            "is_verified": bool(cand.is_verified), "success_count": cand.success_count, "score": float(score)
                        })
                if results:
                    return sorted(results, key=lambda x: x["score"], reverse=True)[:limit]

            # 3. Fallback Keyword
            q = select(CachedQuery).where(
                CachedQuery.namespace == namespace,
                CachedQuery.user_request.like(f"%{request_text}%")
            )
            if verified_only:
                q = q.where(CachedQuery.is_verified == 1)
            
            rows = (await session.execute(q.limit(limit))).scalars().all()
            return [{
                "id": r.id, "user_request": r.user_request, "promql_query": r.promql_query,
                "is_verified": bool(r.is_verified), "success_count": r.success_count, "score": 0.5
            } for r in rows]

    async def add(self, request_text: str, promql_query: str, namespace: str = "default", is_verified: bool = False, metadata: Dict = None) -> bool:
        """Save or update a query in unified memory."""
        try:
            embedding = self.get_embedding(request_text)
            embedding_blob = embedding.tobytes() if embedding is not None else None
            metadata_str = json.dumps(metadata) if metadata else None

            async with self.session_maker() as session:
                # Manual Upsert (SQLite style)
                q = select(CachedQuery).where(
                    CachedQuery.user_request == request_text.strip(),
                    CachedQuery.namespace == namespace
                )
                existing = (await session.execute(q)).scalars().first()
                
                if existing:
                    existing.promql_query = promql_query.strip()
                    existing.embedding = embedding_blob
                    existing.metadata_json = metadata_str
                    if is_verified:
                        existing.is_verified = 1
                else:
                    new_entry = CachedQuery(
                        user_request=request_text.strip(),
                        promql_query=promql_query.strip(),
                        namespace=namespace,
                        is_verified=1 if is_verified else 0,
                        metadata_json=metadata_str,
                        embedding=embedding_blob
                    )
                    session.add(new_entry)
                
                await session.commit()
            return True
        except Exception as e:
            logger.error(f"Error saving to memory: {e}")
            return False

    async def increment_success(self, entry_id: int):
        async with self.session_maker() as session:
            q = select(CachedQuery).where(CachedQuery.id == entry_id)
            row = (await session.execute(q)).scalars().first()
            if row:
                row.success_count += 1
                if not row.is_verified and row.success_count >= AUTO_VERIFY_THRESHOLD:
                    row.is_verified = 1
                    logger.info(f"Query {entry_id} auto-verified.")
                await session.commit()

    async def delete_entry(self, entry_id: int) -> bool:
        async with self.session_maker() as session:
            q = delete(CachedQuery).where(CachedQuery.id == entry_id)
            result = await session.execute(q)
            await session.commit()
            return result.rowcount > 0

    async def update_entry(self, entry_id: int, user_request: str = None, promql_query: str = None, is_verified: bool = None) -> bool:
        async with self.session_maker() as session:
            q = select(CachedQuery).where(CachedQuery.id == entry_id)
            row = (await session.execute(q)).scalars().first()
            if not row:
                return False
            
            if user_request:
                row.user_request = user_request.strip()
                embedding = self.get_embedding(user_request)
                if embedding is not None:
                    row.embedding = embedding.tobytes()
            if promql_query:
                row.promql_query = promql_query.strip()
            if is_verified is not None:
                row.is_verified = 1 if is_verified else 0
            
            await session.commit()
            return True

    async def get_recent(self, limit: int = 50, namespace: str = "default") -> List[Dict[str, Any]]:
        async with self.session_maker() as session:
            q = select(CachedQuery).where(CachedQuery.namespace == namespace).order_by(CachedQuery.id.desc()).limit(limit)
            rows = (await session.execute(q)).scalars().all()
            return [{
                "id": r.id, "user_request": r.user_request, "promql_query": r.promql_query,
                "is_verified": bool(r.is_verified), "success_count": r.success_count
            } for r in rows]

# Global instance
memory = QueryMemory()
