# mcp_servers/agent_db/ingestion/json_ingestor.py
import json
from typing import List, Dict, Any


def read_json(content: str) -> List[Dict[str, Any]]:
    """Reads JSON array content and returns a list of dictionaries."""
    data = json.loads(content)
    if isinstance(data, list):
        return data
    elif isinstance(data, dict):
        # If it's a single dict, wrap it in a list
        return [data]
    return []
