import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from haystack_integrations.tools.mcp import MCPToolset, StdioServerInfo


def test_search():
    print("Testing search_metric with updated API...")
    try:
        server_info = StdioServerInfo(
            command="python",
            args=["/home/aion-asa/dev/python_mcp_servers/mcp-server-demo1/main.py"],
        )
        toolset = MCPToolset(server_info=server_info, eager_connect=True)

        # Find search_metric tool
        search_tool = next(
            (t for t in toolset.tools if t.name == "search_metric"), None
        )
        if search_tool:
            print("\nTesting search_metric(metric_name='node_cpu')...")
            result = search_tool.invoke(metric_name="node_cpu")
            print(f"Result:\n{result}")
        else:
            print("search_metric tool not found!")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_search()
