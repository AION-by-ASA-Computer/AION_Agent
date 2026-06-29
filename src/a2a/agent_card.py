from pydantic import BaseModel
from typing import List, Dict, Any, Optional


class AgentCard(BaseModel):
    """
    Manifesto pubblico dell'agente per il protocollo Agent-to-Agent.
    Permette ad altri agenti di capire se questo profilo è adatto al task.
    """

    agent_id: str
    name: str
    description: str
    version: str = "3.0.0"
    capabilities: List[str] = []
    supported_protocols: List[str] = ["json-rpc/a2a-v1"]
    endpoint: Optional[str] = None

    # Metadati per la negoziazione (costi, trust, etc)
    metadata: Dict[str, Any] = {}


def get_agent_card(profile_name: str, base_url: str = "") -> AgentCard:
    # In un caso reale, carichiamo dal profilo YAML
    from src.agent_profile import profile_manager

    p = profile_manager.get_profile(profile_name)

    if not p:
        return AgentCard(
            agent_id="unknown", name=profile_name, description="Profile not found"
        )

    return AgentCard(
        agent_id=profile_name.lower().replace(" ", "_"),
        name=p.name,
        description=p.description,
        capabilities=p.skills,
        endpoint=f"{base_url}/api/v1/a2a",
    )
