# ═════════════════════════════════════════════════════════════════════════════
# ── NAMESPACE: tool/*  ───────────────────────────────────────────────────────
#
# Native environment tools are different from skills:
#   • They run directly on the host (or a thin sandbox), no Docker needed.
#   • They expose a JSON-Schema input/output contract identical to skills.
#   • Examples: shell_exec, fs_read, fs_write, http_get, python_eval, …
# ═════════════════════════════════════════════════════════════════════════════
import time
from enum import Enum
from typing import Any, Optional, List, Dict
from pydantic import BaseModel, Field
from a2e.caps.base.protocol import (
    A2EMessage,
    A2EEvent,
)


class ToolErrorCode(str, Enum):
    # Tool-specific
    UNKNOWN_TOOL = "unknown_tool"
    TOOL_DENIED = "tool_denied"       # capability check failed
    TOOL_ERROR = "tool_error"


class ToolParameter(BaseModel):
    """Tool parameter definition"""
    name: str = Field(description="Parameter name")
    type: str = \
        Field(
            description="Parameter type (string, integer, boolean, object, array)"
        )
    description: str = Field(description="Parameter description")
    required: bool = Field(default=False)
    enum: Optional[List[str]] = \
        Field(default=None, description="Allowed values for enum types")
    properties: Optional[Dict[str, 'ToolParameter']] = Field(
        default=None,
        description="Nested properties for object types"
    )


class ToolDefinition(BaseModel):
    """
    Definition for a native tool
    Serialised as part of ToolListResponse.
    """
    name: str
    description: str
    input_parameters: List[ToolParameter] = Field(default_factory=list)
    output_parameters: List[ToolParameter] = Field(default_factory=list)
    # input_schema: dict = Field(default_factory=dict)
    # output_schema: dict = Field(default_factory=dict)

    # Security: which session capabilities are required to invoke this tool
    # required_caps: list[str] = Field(default_factory=list)

    # Whether the tool streams partial output before the final response
    streaming: bool = True

    # Safe-to-retry flag (idempotent tools only)
    idempotent: bool = False
    tags: list[str] = Field(default_factory=list)
    version: str = "1.0.0"
    toolkit: Optional[str] = None  # Which toolkit binds it.


class MessageType(str, Enum):
    # Discovery
    TOOL_LIST_REQ = "tool/list/req"
    TOOL_LIST_RESP = "tool/list/resp"
    TOOL_EVENT = "tool/event"
    TOOL_CALL_REQ = "tool/call/req"
    TOOL_CALL_RESP = "tool/call/resp"


class ToolListRequest(A2EMessage):
    """Agent → Host.  Enumerate available native tools."""
    type: MessageType = MessageType.TOOL_LIST_REQ
    filter_kind: str = ""       # empty = return all
    filter_tags: list[str] = Field(default_factory=list)


class ToolListResponse(A2EMessage):
    """Host → Agent.  Returns all available tool manifests."""
    type: MessageType = MessageType.TOOL_LIST_RESP
    req_id: str = ""
    tools: List[ToolDefinition] = Field(default_factory=list)   # list[ToolDefinition]


class ToolCallRequest(A2EMessage):
    """
    Agent → Host.  Execute a native tool.

    `session_id`    — from HandshakeResponse (same session as skills)
    `tool_name`     — must match a ToolDefinition.name
    `input`         — validated against tool's input_schema
    `correlation_id`— ties this call to an agent turn for tracing / learning
    `timeout`       — per-call wall-clock limit (seconds)
    `streaming`     — if True, host emits ToolEvent messages
                      before the final resp
    """
    type: MessageType = MessageType.TOOL_CALL_REQ
    session_id: str = ""
    tool_name: str = ""
    arguments: Dict[str, Any]
    correlation_id: str = ""
    streaming: bool = False
    timeout: int = 30


class ToolEvent(A2EEvent):
    """
    Host → Agent.  Zero or more streaming events during a tool call.

    kind values (reuses EventKind):
      progress  → { pct: int, message: str }
      status    → { message: str }
      artifact  → { name: str, mime: str, chunk: str (base64), final: bool }
      log       → { level: str, message: str }
    """
    type: MessageType = MessageType.TOOL_EVENT


# ─────────────────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────────────────
class ToolResult(BaseModel):
    success: bool
    tool_name: str

    data: Optional[Any] = None
    summary: Optional[Any] = None
    truncated: Optional[bool] = False

    exit_code: int | None = None
    error: str | None = None
    error_code: str | None = None
    duration_ms: int

    events: list[ToolEvent] = Field(default_factory=list)

    def raise_for_error(self) -> "ToolResult":
        if not self.success:
            raise RuntimeError(
                f"Tool {self.tool_name} failed [{self.error_code}]: {self.error}"
            )
        return self


class ToolCallResponse(A2EMessage):
    """Host → Agent.  Final result of a tool call."""
    type: MessageType = MessageType.TOOL_CALL_RESP
    req_id: str = ""
    data: ToolResult
    created_at: float = Field(default_factory=time.time)


TOOL_TYPE_MAP = {
    MessageType.TOOL_LIST_REQ: ToolListRequest,
    MessageType.TOOL_LIST_RESP: ToolListResponse,
    MessageType.TOOL_CALL_REQ: ToolCallRequest,
    MessageType.TOOL_EVENT: ToolEvent,
    MessageType.TOOL_CALL_RESP: ToolCallResponse,
}
