from a2e.caps.tools.client import ToolAPI


def run_tool(client):
    # ─────────────────────────────────────────────
    # List available tools
    # ─────────────────────────────────────────────
    tool = ToolAPI(client)
    tools = tool.list()

    print("Available tools:")
    for t in tools:
        print(f"- {t.name}: {t.description}")

    # ─────────────────────────────────────────────
    # Call a tool (simple)
    # ─────────────────────────────────────────────
    result = tool.call(
        tool_name="read_file",
        arguments={"path": "/tmp/test-generator.log"},
    )

    print("Result:")
    print(result)
