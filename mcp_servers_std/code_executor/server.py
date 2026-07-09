from fastmcp import FastMCP
import os
import sys

# Ensure src is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.tools.code_tools import CodeExecutor
from src.config import config

mcp = FastMCP("AION Code Executor")

_executor = CodeExecutor()


@mcp.tool()
def execute_code(code: str) -> str:
    """
    Esegue codice Python. Il risultato deve essere assegnato alla variabile 'result'.
    Esempio: 'import numpy as np; result = np.mean([1, 2, 3])'
    """
    return _executor.execute(code)


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
                f.write(f"\n--- CODE CRASH ---\n{traceback.format_exc()}\n")
            raise e

    asyncio.run(main())
