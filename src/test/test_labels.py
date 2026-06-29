import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from haystack_integrations.tools.mcp import MCPToolset, StdioServerInfo


def test_label_discovery():
    print("Testing get_metric_labels tool...")
    try:
        server_info = StdioServerInfo(
            command="python",
            args=["/home/aion-asa/dev/python_mcp_servers/mcp-server-demo1/main.py"],
        )
        toolset = MCPToolset(server_info=server_info, eager_connect=True)

        print(f"\nLoaded {len(toolset.tools)} tools:")
        for t in toolset.tools:
            print(f"  - {t.name}")

        # Find get_metric_labels tool
        label_tool = next(
            (t for t in toolset.tools if t.name == "get_metric_labels"), None
        )
        if label_tool:
            print(
                "\nTesting get_metric_labels(metric_name='node_cpu_seconds_total', limit=10)..."
            )
            result = label_tool.invoke(metric_name="node_cpu_seconds_total", limit=10)
            print(f"Result:\n{result}")
        else:
            print("get_metric_labels tool not found!")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_label_discovery()
