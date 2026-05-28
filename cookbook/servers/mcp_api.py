import pdb
from a2e.caps.mcp.client import MCPAPI


def run_mcp(client):
    # ─────────────────────────────────────────────
    # Init MCP API (gateway-backed)
    # ─────────────────────────────────────────────
    mcp = MCPAPI(client)

    # ─────────────────────────────────────────────
    # List registered servers (via gateway)
    # ─────────────────────────────────────────────
    pdb.set_trace()
    servers = mcp.list_servers()

    print("\n=== MCP Servers ===")
    for s in servers:
        print(f"- {s.name} | status={getattr(s, 'status', 'unknown')}")

    # ─────────────────────────────────────────────
    # List available tools (via gateway)
    # ─────────────────────────────────────────────
    tools = mcp.list_tools()

    print("\n=== Available Tools ===")
    for t in tools:
        print(f"- {t.name}: {getattr(t, 'description', '')}")

    # ─────────────────────────────────────────────
    # Call a tool (gateway-routed)
    # ─────────────────────────────────────────────
    print("\n=== Calling Tool ===")

    result = mcp.call_tool(
        tool_name="read_file",
        arguments={"path": "/tmp/test-generator.log"},
        strategy="auto",              # let gateway decide
        # preferred_server="fs",      # optional override
        streaming=False,
    )

    # ─────────────────────────────────────────────
    # Output result
    # ─────────────────────────────────────────────
    print("\n=== Result ===")

    # Depending on your schema (dict vs model)
    if isinstance(result, dict):
        print("Success:", result.get("success"))
        print("Data:", result.get("data"))
        print("Metadata:", result.get("metadata"))
    else:
        # If using pydantic model
        print(result)
