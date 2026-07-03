from fastmcp import FastMCP
import os
import sys
from typing import Optional, List, Dict, Any

# Ensure src is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.memory.mem0_manager import mem0_manager

mcp = FastMCP("AION Semantic Memory")


@mcp.tool()
def search_memories(query: str, user_id: str = "admin", limit: int = 5) -> str:
    """
    Search semantic memories and facts in the agent long-term memory.
    Useful to retrieve user preferences, past decisions, or general facts.
    """
    results = mem0_manager.search_facts(query, user_id=user_id, limit=limit)
    if not results:
        return "No semantically similar memory found."

    output = "Memories found:\n\n"
    for r in results:
        text = r.get("text", str(r))
        score = r.get("score", 0.0)
        output += f"- {text} (Relevance: {score:.2f})\n"
    return output


@mcp.tool()
def add_memory_fact(text: str, user_id: str = "admin") -> str:
    """
    Save a new fact or preference to long-term memory.
    Use when the user shares something important to remember.
    """
    res = mem0_manager.add_fact(text, user_id=user_id)
    return f"Fact stored successfully. ID: {res}"


@mcp.tool()
def list_all_memories(user_id: str = "admin") -> str:
    """List all facts stored for the current user."""
    results = mem0_manager.get_all_facts(user_id=user_id)
    if not results:
        return "Memory is currently empty."

    output = "Full semantic memory list:\n\n"
    for r in results:
        text = r.get("text", str(r))
        fid = r.get("id", "N/A")
        output += f"- [{fid}] {text}\n"
    return output


@mcp.tool()
def delete_memory_fact(fact_id: str) -> str:
    """Delete a specific fact from memory using its ID."""
    success = mem0_manager.delete_fact(fact_id)
    return (
        f"Memory {fact_id} deleted successfully."
        if success
        else "ID not found or error during deletion."
    )


if __name__ == "__main__":
    # Avvia come server SSE su porta 8002 per isolamento e modularità
    print(f"🚀 Avvio AION Semantic Memory (Mem0) su porta 8002 via SSE...")
    mcp.run(transport="sse", host="0.0.0.0", port=8002)
