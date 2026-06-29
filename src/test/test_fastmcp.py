import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from haystack_integrations.tools.mcp import MCPToolset, StdioServerInfo


def test_fastmcp():
    print("Connecting to FastMCP Server via STDIO...")
    try:
        server_info = StdioServerInfo(
            command="python",
            args=["/home/aion-asa/dev/python_mcp_servers/mcp-server-demo1/main.py"],
        )
        toolset = MCPToolset(server_info=server_info, eager_connect=True)

        tools = toolset.tools
        print(f"Successfully connected! Found {len(tools)} tools:")
        for tool in tools:
            print(f"\n - Name: {tool.name}")
            print(f"   Description: {tool.description}")
            print(f"   Parameters: {tool.parameters}")
            print("-" * 50)

    except Exception as e:
        print(f"Failed to connect or list tools: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_fastmcp()
