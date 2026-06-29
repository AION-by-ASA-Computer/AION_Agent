import asyncio
import os
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def diagnose_server(server_path: str):
    print(f"--- Diagnostica Server: {server_path} ---")
    
    # Use absolute paths and current python
    python_exe = sys.executable
    abs_server_path = os.path.abspath(server_path)
    
    server_params = StdioServerParameters(
        command=python_exe,
        args=["-u", abs_server_path],
        env=os.environ.copy()
    )
    
    try:
        print("Tento la connessione stdio...")
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                print("Inizializzazione sessione MCP...")
                await session.initialize()
                
                print("Richiedo la lista dei tool...")
                tools_result = await session.list_tools()
                
                print(f"✅ Successo! Tool trovati: {[t.name for t in tools_result.tools]}")
                return True
    except Exception as e:
        print(f"❌ FALLIMENTO: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        target = "mcp_servers/prometheus/server.py"
    else:
        target = sys.argv[1]
        
    asyncio.run(diagnose_server(target))
