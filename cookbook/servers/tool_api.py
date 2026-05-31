from a2e.caps.tools.client import ToolAPI
from a2e.caps.tools.protocol import ToolEvent


def on_tool_event(evt: ToolEvent):
    """Receive streaming events during a tool call."""
    print(f"  [tool.event] kind={evt.kind} | data={evt.data}")


def run_tool(client):
    # --- List available tools ---
    tool = ToolAPI(client)
    tools = tool.list()

    print("Available tools:")
    for t in tools:
        print(f"- {t.name}: {t.description}")

    # --- Call a tool ---
    result = tool.call(
        tool_name="read_file",
        arguments={"path": "/tmp/test-generator.log"},
    )

    print("Result:")
    print(result)

    # --- Call a tool with streaming events ---
    print("\n--- Streaming tool call ---")
    result = tool.call(
        tool_name="read_file",
        arguments={"path": "/tmp/test-generator.log"},
        streaming=True,
        on_event=on_tool_event,
    )

    print("Final result:")
    print(result)
