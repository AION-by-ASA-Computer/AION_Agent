from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import BaseModel
from typing import Dict, Any, Optional
from ..a2a.agent_card import get_agent_card
from ..main import get_agent
from ..agent_pipeline import AgentPipeline
import json
import uuid

router = APIRouter(prefix="/a2a", tags=["agent-to-agent"])


class A2AMessage(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    params: Dict[str, Any]
    id: Optional[str] = None


@router.get("/card/{profile_name}")
async def read_agent_card(profile_name: str, request: Request):
    base_url = str(request.base_url).rstrip("/")
    return get_agent_card(profile_name, base_url=base_url)


@router.post("/invoke")
async def invoke_agent(msg: A2AMessage, x_aion_origin: str = Header(None)):
    """
    JSON-RPC entry point per chiamate Agent-to-Agent.
    Permette a un agente esterno di inviare un prompt e ricevere una risposta.
    """
    if msg.method != "agent.ask":
        raise HTTPException(
            status_code=400, detail="Method not supported. Use 'agent.ask'"
        )

    profile_name = msg.params.get("profile", "AION Core")
    prompt = msg.params.get("prompt")
    session_id = msg.params.get("session_id", f"a2a_{uuid.uuid4().hex[:8]}")

    if not prompt:
        raise HTTPException(status_code=400, detail="Missing 'prompt' in params")

    try:
        # 1. Get the agent instance
        agent_instance, p_name = await get_agent(
            profile_name,
            session_id=session_id,
            user_id=f"a2a_{x_aion_origin or 'external'}",
        )

        # 2. Setup pipeline
        pipeline = AgentPipeline(
            agent_instance, session_id=session_id, profile_name=p_name, user_id="a2a"
        )

        # 3. Run (A2A è tipicamente sincrono/bloccante via JSON-RPC)
        result = await pipeline.run(prompt)

        return {
            "jsonrpc": "2.0",
            "id": msg.id,
            "result": {
                "text": result.get("text"),
                "session_id": session_id,
                "agent": p_name,
            },
        }
    except Exception as e:
        return {
            "jsonrpc": "2.0",
            "id": msg.id,
            "error": {"code": -32000, "message": str(e)},
        }
