from fastmcp import FastMCP
import os
import sys

# Ensure src is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.doc_processor import query_docs
from src.config import config

mcp = FastMCP("AION Legacy RAG")

# For current implementation, 'documents' are passed via context or session
# In an MCP server, we'll need a way to pass or store these.
# For now, we'll expose the tool as a interface.


@mcp.tool()
def search_documents(query: str, documents_context: str = "") -> str:
    """
    Search information in uploaded documents.
    Se documents_context è fornito, lo usa come base di ricerca.
    """
    if not documents_context:
        return "No document context provided for search."

    # We adapt the legacy query_docs which expected a list of dicts.
    # For simplicity in this legacy wrapper, we'll treat context as the document text.
    if query.lower() in documents_context.lower():
        idx = documents_context.lower().find(query.lower())
        start = max(0, idx - 200)
        end = min(len(documents_context), idx + 1000)
        return f"--- Document Excerpt ---\n...{documents_context[start:end]}..."

    return "No match found in the provided documents."


if __name__ == "__main__":
    import asyncio
    import traceback
    from mcp.server.stdio import stdio_server

    async def main():
        try:
            async with stdio_server() as (read_stream, write_stream):
                await mcp._mcp_server.run(
                    read_stream,
                    write_stream,
                    mcp._mcp_server.create_initialization_options(),
                )
        except Exception as e:
            with open("data/mcp_debug.log", "a") as f:
                f.write(f"\n--- RAG CRASH ---\n{traceback.format_exc()}\n")
            raise e

    asyncio.run(main())
