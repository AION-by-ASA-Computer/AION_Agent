#!/usr/bin/env bash
# Test minimale POST /chat con curl (header + primi byte SSE).
# Uso: ./scripts/test_aion_chat_sse.sh [BASE_URL]
set -euo pipefail
BASE="${1:-http://127.0.0.1:8001}"
SID="$(uuidgen 2>/dev/null || python3 -c 'import uuid; print(uuid.uuid4())')"
echo "[test] POST ${BASE}/chat session_id=${SID}"
curl -sS -N --max-time 60 \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-AION-User-Id: default" \
  -d "{\"message\":\"ping\",\"session_id\":\"${SID}\",\"profile\":\"Generic Assistant\",\"user_id\":\"default\",\"reasoning_effort\":\"min\"}" \
  "${BASE}/chat" | head -c 4000 | sed 's/\r$//' || true
echo
echo "[test] done (truncated with head -c 4000)"
