from enum import Enum
from pydantic import BaseModel, Field
from typing import Dict, List, Any, Optional
from a2e.caps.base import A2EMessage


TOOLKIT_VERSION = "1.0"


class MessageType(str, Enum):
    # Discovery
    TOOLKIT_LIST_REQ = "toolkit/list/req"
    TOOLKIT_LIST_RESP = "toolkit/list/resp"
    TOOLKIT_CONFIGURE_REQ = "toolkit/configure/req"
    TOOLKIT_CONFIGURE_RESP = "toolkit/configure/resp"


class ToolkitDefinition(BaseModel):
    name: str
    alias: str = ""
    description: str = ""

    # UI metadata
    category: str = ""
    tags: List[str] = []
    icon_svg: Optional[str] = None

    # Schema (CRITICAL)
    schema: Dict[str, Any] = Field(default_factory=dict)

    tools: List[str]

    # Runtime info
    configured: bool = False
    version: str = "1.0.0"


class ToolkitListRequest(A2EMessage):
    """Agent → Host.  Enumerate available native tools."""
    type: str = MessageType.TOOLKIT_LIST_REQ
    filter_kind: str = ""       # empty = return all
    filter_tags: list[str] = Field(default_factory=list)


class ToolkitListResponse(A2EMessage):
    """Host → Agent.  Returns all available tool manifests."""
    type: str = MessageType.TOOLKIT_LIST_RESP
    req_id: str = ""
    toolkits: list[ToolkitDefinition] = Field(default_factory=list)


# ─────────────────────────────────────────────
# TOOLKIT CONFIGURATION
# ─────────────────────────────────────────────
class ToolkitConfigureRequest(A2EMessage):
    """
    Agent → Host

    Configure / initialize a toolkit instance with schema + credentials.
    """
    type: MessageType = MessageType.TOOLKIT_CONFIGURE_REQ

    session_id: str = ""
    toolkit_name: str = ""
    config: Dict[str, Any] = Field(default_factory=dict)


class ToolkitConfigureResponse(A2EMessage):
    """
    Host → Agent

    Acknowledges toolkit configuration.
    """
    type: MessageType = MessageType.TOOLKIT_CONFIGURE_RESP

    req_id: str = ""
    toolkit_name: str = ""
    status: str = "ok"
    message: Optional[str] = None


TOOLKIT_TYPE_MAP = {
    MessageType.TOOLKIT_LIST_REQ: ToolkitListRequest,
    MessageType.TOOLKIT_LIST_RESP: ToolkitListResponse,
    MessageType.TOOLKIT_CONFIGURE_REQ: ToolkitConfigureRequest,
    MessageType.TOOLKIT_CONFIGURE_RESP: ToolkitConfigureResponse,

}
