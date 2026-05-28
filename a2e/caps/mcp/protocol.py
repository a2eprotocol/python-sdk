# ═════════════════════════════════════════════════════════════════════════════
# ── NAMESPACE: mcp/*  ────────────────────────────────────────────────────────
#
# MCP (Model Context Protocol) bridge namespace.
#
# A2E acts as an MCP *client*. The A2E host connects to one or more MCP servers
# (over stdio subprocess or HTTP+SSE) and proxies their capabilities:
#
#   MCP Tools      → appear in tool/list/resp with source="mcp"
#                    callable via tool/call/req (transparent)
#   MCP Resources  → mcp/resource/list + mcp/resource/read
#   MCP Prompts    → mcp/prompt/list + mcp/prompt/get
#   MCP Sampling   → mcp/sample/req (server asks agent to run LLM)
#   MCP Roots      → mcp/roots/list (agent exposes accessible paths)
# ═════════════════════════════════════════════════════════════════════════════
import uuid
from enum import Enum
from pydantic import BaseModel, Field
from a2e.caps.base.protocol import A2EMessage


class MessageType(str, Enum):
    MCP_SERVER_LIST_REQ = "mcp/server/list/req"
    MCP_SERVER_LIST_RESP = "mcp/server/list/resp"
    MCP_SERVER_REGISTER_REQ = "mcp/server/register/req"
    MCP_SERVER_REGISTER_RESP = "mcp/server/register/resp"
    MCP_SERVER_UNREGISTER_REQ = "mcp/server/unregister/req"
    MCP_SERVER_UNREGISTER_RESP = "mcp/server/unregister/resp"
    MCP_SERVER_PUSH = "mcp/server/push"
    MCP_RESOURCE_LIST_REQ = "mcp/resource/list/req"
    MCP_RESOURCE_LIST_RESP = "mcp/resource/list/resp"
    MCP_RESOURCE_READ_REQ = "mcp/resource/read/req"
    MCP_RESOURCE_READ_RESP = "mcp/resource/read/resp"
    MCP_RESOURCE_SUBSCRIBE_REQ = "mcp/resource/subscribe/req"
    MCP_RESOURCE_SUBSCRIBE_RESP = "mcp/resource/subscribe/resp"
    MCP_PROMPT_LIST_REQ = "mcp/prompt/list/req"
    MCP_PROMPT_LIST_RESP = "mcp/prompt/list/resp"
    MCP_PROMPT_GET_REQ = "mcp/prompt/get/req"
    MCP_PROMPT_GET_RESP = "mcp/prompt/get/resp"
    MCP_SAMPLE_REQ = "mcp/sample/req"
    MCP_SAMPLE_RESP = "mcp/sample/resp"
    MCP_ROOT_LIST_REQ = "mcp/root/list/req"
    MCP_ROOT_LIST_RESP = "mcp/root/list/resp"


class MCPTransport(str, Enum):
    """Wire transport used to reach the MCP server."""
    STDIO = "stdio"   # spawn subprocess, communicate via stdin/stdout
    SSE = "sse"     # HTTP + Server-Sent Events (MCP HTTP transport)
    WS = "ws"      # WebSocket (reserved)


class MCPServerStatus(str, Enum):
    CONNECTING = "connecting"
    READY = "ready"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class MCPServerConfig(BaseModel):
    """
    Connection configuration for one MCP server.

    STDIO example:
      { "transport": "stdio",
        "cmd": ["npx","-y","@modelcontextprotocol/server-filesystem","/tmp"],
        "name": "filesystem" }

    SSE example:
      { "transport": "sse",
        "url": "https://mcp.example.com/sse",
        "headers": { "Authorization": "Bearer sk-..." },
        "name": "remote-tools" }
    """
    server_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = ""
    transport: str = MCPTransport.STDIO.value
    # stdio
    cmd: list[str] = Field(default_factory=list)
    cwd: str = ""
    env: dict = Field(default_factory=dict)
    # sse / ws
    url: str = ""
    headers: dict = Field(default_factory=dict)
    # common
    timeout: int = 300
    auto_reconnect: bool = True
    tool_allow_list: list[str] = Field(default_factory=list)
    resource_allow_list: list[str] = Field(default_factory=list)


class MCPServerInfo(BaseModel):
    """Runtime status of a registered MCP server."""
    server_id: str
    name: str
    transport: str
    status: str = MCPServerStatus.DISCONNECTED.value
    mcp_version: str = ""
    server_name: str = ""
    server_version: str = ""
    tools_count: int = 0
    resources_count: int = 0
    prompts_count: int = 0
    last_ping_ms: float = 0.0
    error: str = ""
    connected_at: float = 0.0


class MCPServerRegisterRequest(A2EMessage):
    """Agent → Host.  Register and connect to a new MCP server."""
    type: MessageType = MessageType.MCP_SERVER_REGISTER_REQ
    config: dict = Field(default_factory=dict)   # MCPServerConfig


class MCPServerRegisterResponse(A2EMessage):
    """Host → Agent.  Returns runtime info after MCP initialize completes."""
    type: MessageType = MessageType.MCP_SERVER_REGISTER_RESP
    req_id: str = ""
    ok: bool = False
    server: dict = Field(default_factory=dict)   # MCPServerInfo
    error: str = ""


class MCPServerListRequest(A2EMessage):
    """Agent → Host.  List all registered MCP servers and their status."""
    type: MessageType = MessageType.MCP_SERVER_LIST_REQ
    status_filter: str = ""   # empty = all


class MCPServerListResponse(A2EMessage):
    type: MessageType = MessageType.MCP_SERVER_LIST_RESP
    req_id: str = ""
    servers: list[dict] = Field(default_factory=list)   # list[MCPServerInfo]


class MCPServerUnregisterRequest(A2EMessage):
    """Agent → Host.  Disconnect and remove an MCP server."""
    type: MessageType = MessageType.MCP_SERVER_UNREGISTER_REQ
    server_id: str = ""


class MCPServerUnregisterResponse(A2EMessage):
    type: MessageType = MessageType.MCP_SERVER_UNREGISTER_RESP
    req_id: str = ""
    ok: bool = False
    server_id: str = ""


class MCPServerPush(A2EMessage):
    """
    Host → Agent (server-initiated).  Forwarded MCP server notification.

    MCP notification methods forwarded:
      notifications/tools/list_changed
      notifications/resources/list_changed
      notifications/resources/updated
      notifications/prompts/list_changed
      notifications/progress
      notifications/message  (log)
    """
    type: MessageType = MessageType.MCP_SERVER_PUSH
    server_id: str = ""
    method: str = ""
    params: dict = Field(default_factory=dict)


class MCPResource(BaseModel):
    """Mirrors the MCP Resource object."""
    uri: str
    name: str = ""
    description: str = ""
    mime_type: str = ""
    server_id: str = ""
    annotations: dict = Field(default_factory=dict)


class MCPResourceListRequest(A2EMessage):
    """Agent → Host.  List resources across all (or one) MCP server(s)."""
    type: MessageType = MessageType.MCP_RESOURCE_LIST_REQ
    server_id: str = ""
    cursor: str = ""


class MCPResourceListResponse(A2EMessage):
    type: str = "mcp/resource/list/resp"
    req_id: str = ""
    resources: list[dict] = Field(default_factory=list)   # list[MCPResource]
    next_cursor: str = ""


class MCPResourceReadRequest(A2EMessage):
    """Agent → Host.  Read a resource by URI."""
    type: MessageType = MessageType.MCP_RESOURCE_READ_REQ
    uri: str = ""
    server_id: str = ""


class MCPResourceContent(BaseModel):
    """One content block in a resource read response."""
    uri: str
    mime_type: str = "text/plain"
    text: str = ""
    blob: str = ""   # base64 for binary
    type: str = "text"   # "text" | "blob"


class MCPResourceReadResponse(A2EMessage):
    type: MessageType = MessageType.MCP_RESOURCE_READ_RESP
    req_id: str = ""
    contents: list[dict] = Field(default_factory=list)   # list[MCPResourceContent]
    server_id: str = ""
    error: str = ""


class MCPResourceSubscribeRequest(A2EMessage):
    """
    Agent → Host.  Subscribe to change notifications for a resource URI.
    Changes are forwarded as mcp/server/push with
    method="notifications/resources/updated".
    """
    type: MessageType = MessageType.MCP_RESOURCE_SUBSCRIBE_REQ
    uri: str = ""
    server_id: str = ""


class MCPResourceSubscribeResponse(A2EMessage):
    type: MessageType = MessageType.MCP_RESOURCE_SUBSCRIBE_RESP
    req_id: str = ""
    ok: bool = False
    error: str = ""


# ── MCP Prompts ───────────────────────────────────────────────────────────────
class MCPPrompt(BaseModel):
    """Mirrors the MCP Prompt object."""
    name: str
    description: str = ""
    server_id: str = ""
    arguments: list[dict] = Field(default_factory=list)
    # argument shape: { "name": str, "description": str, "required": bool }


class MCPPromptListRequest(A2EMessage):
    """Agent → Host.  List all prompt templates."""
    type: MessageType = MessageType.MCP_PROMPT_LIST_REQ
    server_id: str = ""
    cursor: str = ""


class MCPPromptListResponse(A2EMessage):
    type: MessageType = MessageType.MCP_PROMPT_LIST_RESP
    req_id: str = ""
    prompts: list[dict] = Field(default_factory=list)   # list[MCPPrompt]
    next_cursor: str = ""


class MCPPromptGetRequest(A2EMessage):
    """
    Agent → Host.  Render a prompt template with supplied argument values.
    Returns a list of LLM-ready messages.
    """
    type: MessageType = MessageType.MCP_PROMPT_GET_REQ
    name: str = ""
    arguments: dict = Field(default_factory=dict)
    server_id: str = ""


class MCPPromptMessage(BaseModel):
    """One message in a rendered prompt (role + structured content)."""
    role: str   # "user" | "assistant"
    content: dict  # { "type": "text"|"image"|"resource", "text": str, ... }


class MCPPromptGetResponse(A2EMessage):
    type: MessageType = MessageType.MCP_PROMPT_GET_RESP
    req_id: str = ""
    description: str = ""
    messages: list[dict] = Field(default_factory=list)   # list[MCPPromptMessage]
    server_id: str = ""
    error: str = ""


# ── MCP Sampling (server → agent LLM call) ───────────────────────────────────

class MCPSamplingRequest(A2EMessage):
    """
    Host → Agent (server-initiated).
    An MCP server is requesting the agent perform an LLM completion.
    Maps 1-to-1 with MCP's sampling/createMessage request.
    The agent MAY refuse by setting error in MCPSamplingResponse.
    """
    type: MessageType = MessageType.MCP_SAMPLE_REQ
    server_id: str = ""
    mcp_request_id: str = ""
    messages: list[dict] = Field(default_factory=list)
    model_preferences: dict = Field(default_factory=dict)
    system_prompt: str = ""
    include_context: str = "none"   # "none"|"thisServer"|"allServers"
    temperature: float = 1.0
    max_tokens: int = 1024
    stop_sequences: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class MCPSamplingResponse(A2EMessage):
    """Agent → Host.  Forwarded back to the originating MCP server."""
    type: str = MessageType.MCP_SAMPLE_REQ
    req_id: str = ""
    server_id: str = ""
    mcp_request_id: str = ""
    role: str = "assistant"
    content: dict = Field(default_factory=dict)
    # content shape: { "type": "text", "text": "..." }
    model: str = ""
    stop_reason: str = ""   # "endTurn"|"stopSequence"|"maxTokens"
    error: str = ""


# ── MCP Roots ─────────────────────────────────────────────────────────────────

class MCPRoot(BaseModel):
    """A filesystem root path the agent exposes to MCP servers."""
    uri: str
    name: str = ""


class MCPRootsListRequest(A2EMessage):
    """Host → Agent (server-initiated).  MCP server asking for roots."""
    type: MessageType = MessageType.MCP_ROOT_LIST_REQ
    server_id: str = ""
    mcp_request_id: str = ""


class MCPRootsListResponse(A2EMessage):
    """Agent → Host.  Roots the agent exposes."""
    type: MessageType = MessageType.MCP_ROOT_LIST_RESP
    req_id: str = ""
    server_id: str = ""
    mcp_request_id: str = ""
    roots: list[dict] = Field(default_factory=list)   # list[MCPRoot]


# ── MCP-specific error codes ──────────────────────────────────────────────────

class MCPErrorCode(str, Enum):
    MCP_SERVER_NOT_FOUND = "mcp_server_not_found"
    MCP_SERVER_UNAVAILABLE = "mcp_server_unavailable"
    MCP_TOOL_NOT_FOUND = "mcp_tool_not_found"
    MCP_RESOURCE_NOT_FOUND = "mcp_resource_not_found"
    MCP_PROMPT_NOT_FOUND = "mcp_prompt_not_found"
    MCP_TRANSPORT_ERROR = "mcp_transport_error"
    MCP_PROTOCOL_ERROR = "mcp_protocol_error"
    MCP_SAMPLING_REFUSED = "mcp_sampling_refused"
    MCP_CAPABILITY_MISSING = "mcp_capability_missing"


# MCP types are also valid in A2E
MCP_TYPE_MAP = {
    MessageType.MCP_SERVER_LIST_REQ: MCPServerListRequest,
    MessageType.MCP_SERVER_LIST_RESP: MCPServerListResponse,

    MessageType.MCP_SERVER_REGISTER_REQ: MCPServerRegisterRequest,
    MessageType.MCP_SERVER_REGISTER_RESP: MCPServerRegisterResponse,

    MessageType.MCP_SERVER_UNREGISTER_REQ: MCPServerUnregisterRequest,
    MessageType.MCP_SERVER_UNREGISTER_RESP: MCPServerUnregisterResponse,

    MessageType.MCP_RESOURCE_LIST_REQ: MCPResourceListRequest,
    MessageType.MCP_RESOURCE_LIST_RESP: MCPResourceListResponse,

    MessageType.MCP_RESOURCE_READ_REQ: MCPResourceReadRequest,
    MessageType.MCP_RESOURCE_READ_RESP: MCPResourceReadResponse,

    MessageType.MCP_RESOURCE_SUBSCRIBE_REQ: MCPResourceSubscribeRequest,
    MessageType.MCP_RESOURCE_SUBSCRIBE_RESP: MCPResourceSubscribeResponse,

    MessageType.MCP_PROMPT_LIST_REQ: MCPPromptListRequest,
    MessageType.MCP_PROMPT_LIST_RESP: MCPPromptListResponse,

    MessageType.MCP_PROMPT_GET_REQ: MCPPromptGetRequest,
    MessageType.MCP_PROMPT_GET_RESP: MCPPromptGetResponse,

    MessageType.MCP_ROOT_LIST_REQ: MCPRootsListRequest,
    MessageType.MCP_ROOT_LIST_RESP: MCPRootsListResponse,

    MessageType.MCP_SAMPLE_REQ: MCPSamplingRequest,  # response from agent
    MessageType.MCP_SAMPLE_RESP: MCPSamplingResponse,  # response from agent
}
