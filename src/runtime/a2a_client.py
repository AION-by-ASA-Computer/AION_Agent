import httpx
import json
from typing import Dict, Any, Optional

class A2AClient:
    """
    Client per delegare task ad altri agenti tramite protocollo A2A.
    Può essere registrato come skill/tool MCP.
    """
    def __init__(self, timeout: int = 60):
        self.timeout = timeout

    async def ask_agent(self, endpoint: str, prompt: str, profile: str = "AION Core", session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Invia una richiesta JSON-RPC a un altro agente AION.
        """
        payload = {
            "jsonrpc": "2.0",
            "method": "agent.ask",
            "params": {
                "prompt": prompt,
                "profile": profile,
                "session_id": session_id
            },
            "id": "a2a_call_1"
        }
        
        headers = {
            "Content-Type": "application/json",
            "X-Aion-Origin": "AION-Agent-Main"
        }
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(endpoint, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                if "error" in data:
                    return {"success": False, "error": data["error"]["message"]}
                    
                return {"success": True, "result": data["result"]["text"], "agent": data["result"]["agent"]}
            except Exception as e:
                return {"success": False, "error": str(e)}

a2a_client = A2AClient()
