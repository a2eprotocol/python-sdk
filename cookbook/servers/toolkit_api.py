from a2e.caps.toolkits.client import ToolkitAPI


def run_toolkit(client):
    toolkit_api = ToolkitAPI(client=client)
    # ─────────────────────────────────────────────
    # Example: List Toolkits (via API)
    # ─────────────────────────────────────────────
    print("[client] Fetching toolkits via ToolkitAPI...")

    toolkits = toolkit_api.list(timeout=50)
    print(f"[client] Available toolkits: {toolkits}")

    # Optional: pretty print
    for tk in toolkits:
        print(
            f"[toolkit] name={tk.name}, "
            f"configured={tk.configured}, "
            f"tools={tk.tools}"
        )
