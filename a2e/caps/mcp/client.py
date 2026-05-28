import pdb
from typing import Dict, List, Optional

from a2e.core.client import A2EClient
from a2e.caps.mcp import (
    MCPServerListRequest,
    MCPServerListResponse,
    MCPServerRegisterRequest,
    MCPServerRegisterResponse,
    MCPServerInfo,
    MCP_TYPE_MAP,
)
from a2e.caps.tools import (
    ToolDefinition
)


class MCPAPI:
    def __init__(self, client: A2EClient):
        self._c = client
        self._c.update_msg_types(MCP_TYPE_MAP)

        # 🔥 Local caches
        self._servers: Dict[str, MCPServerInfo] = {}
        self._tool_index: Dict[str, List[str]] = {}  # tool_name → [server_names]

    # ─────────────────────────────────────────────
    # 🖥️ Server Management
    # ─────────────────────────────────────────────
    def list_servers(self, refresh: bool = True) -> List[MCPServerInfo]:
        if not refresh and self._servers:
            return list(self._servers.values())

        req = MCPServerListRequest()
        resp = self._c.rpc(req, timeout=10)

        if not isinstance(resp, MCPServerListResponse):
            raise ConnectionError(f"Unexpected MCP list response: {type(resp)}")

        self._servers = {
            s.name: MCPServerInfo.model_validate(s)
            for s in resp.servers
        }

        self._rebuild_tool_index()
        return list(self._servers.values())

    def register_server(
        self,
        name: str,
        config: dict,
        capabilities: Optional[dict] = None,
    ) -> MCPServerInfo:
        req = MCPServerRegisterRequest(
            name=name,
            config=config,
            capabilities=capabilities or {},
        )

        resp = self._c.rpc(req, timeout=20)

        if not isinstance(resp, MCPServerRegisterResponse):
            raise ConnectionError(f"Unexpected MCP register response: {type(resp)}")

        server = MCPServerInfo.model_validate(resp.server)

        self._servers[server.name] = server
        self._rebuild_tool_index()

        return server

    # ─────────────────────────────────────────────
    # 🔧 Tool Discovery
    # ─────────────────────────────────────────────
    def list_tools(
        self,
        server_name: Optional[str] = None,
    ) -> List[ToolDefinition]:

        if not self._servers:
            self.list_servers()

        tools: List[ToolDefinition] = []

        if server_name:
            server = self._servers.get(server_name)
            if not server:
                raise ValueError(f"Unknown server: {server_name}")
            tools.extend(server.tools or [])
        else:
            for s in self._servers.values():
                tools.extend(s.tools or [])

        return tools

    def find_tool(
        self,
        tool_name: str,
    ) -> List[str]:
        """
        Returns list of servers that provide this tool
        """
        if not self._tool_index:
            self.list_servers()

        return self._tool_index.get(tool_name, [])

    # ─────────────────────────────────────────────
    # 🚀 Routing + Execution
    # ─────────────────────────────────────────────
    def call_tool(
        self,
        tool_name: str,
        arguments: dict,
        *,
        server_name: Optional[str] = None,
        strategy: str = "first",  # future: round_robin, fallback
        tool_api=None,
        **kwargs,
    ):
        """
        Route tool call via MCP → delegate to ToolAPI
        """

        if not tool_api:
            raise ValueError("ToolAPI instance required")

        # 🔥 Resolve server
        if not server_name:
            candidates = self.find_tool(tool_name)

            if not candidates:
                raise ValueError(f"No server found for tool: {tool_name}")

            if strategy == "first":
                server_name = candidates[0]
            else:
                server_name = candidates[0]  # placeholder

        return tool_api.call(
            tool_name=tool_name,
            arguments=arguments,
            **kwargs,
        )

    # ─────────────────────────────────────────────
    # 🧠 Internal Helpers
    # ─────────────────────────────────────────────
    def _rebuild_tool_index(self):
        self._tool_index.clear()

        for server_name, server in self._servers.items():
            for tool in server.tools or []:
                self._tool_index.setdefault(tool.name, []).append(server_name)
