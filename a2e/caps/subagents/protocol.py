from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# ============================================================================
# ENUMS
# ============================================================================
class MessageType(str, Enum):
    # Spawn
    SUBAGENT_SPAWN_REQ = "SUBAGENT_SPAWN_REQ"
    SUBAGENT_SPAWN_RESP = "SUBAGENT_SPAWN_RESP"

    # Delegate
    SUBAGENT_DELEGATE_REQ = "SUBAGENT_DELEGATE_REQ"
    SUBAGENT_DELEGATE_RESP = "SUBAGENT_DELEGATE_RESP"

    # Await
    SUBAGENT_AWAIT_REQ = "SUBAGENT_AWAIT_REQ"
    SUBAGENT_AWAIT_RESP = "SUBAGENT_AWAIT_RESP"

    # Message
    SUBAGENT_MESSAGE_REQ = "SUBAGENT_MESSAGE_REQ"
    SUBAGENT_MESSAGE_RESP = "SUBAGENT_MESSAGE_RESP"

    # List
    SUBAGENT_LIST_REQ = "SUBAGENT_LIST_REQ"
    SUBAGENT_LIST_RESP = "SUBAGENT_LIST_RESP"

    # Cancel / terminate
    SUBAGENT_CANCEL_REQ = "SUBAGENT_CANCEL_REQ"
    SUBAGENT_TERMINATE_REQ = "SUBAGENT_TERMINATE_REQ"

    # Merge
    SUBAGENT_MERGE_REQ = "SUBAGENT_MERGE_REQ"
    SUBAGENT_MERGE_RESP = "SUBAGENT_MERGE_RESP"

    # Events
    SUBAGENT_EVENT = "SUBAGENT_EVENT"


class SubagentStatus(str, Enum):
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TERMINATED = "TERMINATED"


class MemoryScope(str, Enum):
    SHARED = "shared"
    ISOLATED = "isolated"
    SNAPSHOT = "snapshot"


class ToolScope(str, Enum):
    SHARED = "shared"
    RESTRICTED = "restricted"
    ISOLATED = "isolated"


# ============================================================================
# BASE MODELS
# ============================================================================
class BaseMessage(BaseModel):
    type: MessageType


class SourceRef(BaseModel):
    session_id: Optional[str] = None
    trajectory_id: Optional[str] = None
    turn_id: Optional[str] = None


# ============================================================================
# SUBAGENT CONFIG
# ============================================================================
class SubagentConfig(BaseModel):
    name: str
    role: Optional[str] = None

    model: str
    system_prompt: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    memory_scope: MemoryScope = MemoryScope.SHARED
    tool_scope: ToolScope = ToolScope.RESTRICTED
    max_steps: int = 40
    timeout_seconds: int = 600
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskDefinition(BaseModel):
    name: str
    instruction: str
    success_criteria: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SubagentInfo(BaseModel):
    subagent_id: str
    name: str
    status: SubagentStatus
    parent_agent_id: Optional[str] = None
    root_agent_id: Optional[str] = None
    depth: int = 0
    config: SubagentConfig


# ============================================================================
# SPAWN
# ============================================================================
class SubagentSpawnRequest(BaseMessage):
    type: Literal[
        MessageType.SUBAGENT_SPAWN_REQ
    ] = MessageType.SUBAGENT_SPAWN_REQ

    agent: SubagentConfig

    parent_agent_id: Optional[str] = None
    root_agent_id: Optional[str] = None


class SubagentSpawnResponse(BaseMessage):
    type: Literal[
        MessageType.SUBAGENT_SPAWN_RESP
    ] = MessageType.SUBAGENT_SPAWN_RESP

    subagent_id: str
    status: SubagentStatus


# ============================================================================
# DELEGATE
# ============================================================================
class SubagentDelegateRequest(BaseMessage):
    type: Literal[
        MessageType.SUBAGENT_DELEGATE_REQ
    ] = MessageType.SUBAGENT_DELEGATE_REQ

    subagent_id: str
    task: TaskDefinition


class SubagentDelegateResponse(BaseMessage):
    type: Literal[
        MessageType.SUBAGENT_DELEGATE_RESP
    ] = MessageType.SUBAGENT_DELEGATE_RESP
    accepted: bool = True
    status: SubagentStatus


# ============================================================================
# AWAIT
# ============================================================================
class SubagentAwaitRequest(BaseMessage):
    type: Literal[
        MessageType.SUBAGENT_AWAIT_REQ
    ] = MessageType.SUBAGENT_AWAIT_REQ
    subagent_id: str


class SubagentAwaitResponse(BaseMessage):
    type: Literal[
        MessageType.SUBAGENT_AWAIT_RESP
    ] = MessageType.SUBAGENT_AWAIT_RESP

    subagent_id: str
    status: SubagentStatus
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# ============================================================================
# MESSAGE
# ============================================================================
class SubagentMessagePayload(BaseModel):
    type: str
    content: Any


class SubagentMessageRequest(BaseMessage):
    type: Literal[
        MessageType.SUBAGENT_MESSAGE_REQ
    ] = MessageType.SUBAGENT_MESSAGE_REQ

    from_subagent_id: str
    to_subagent_id: str
    message: SubagentMessagePayload


class SubagentMessageResponse(BaseMessage):
    type: Literal[
        MessageType.SUBAGENT_MESSAGE_RESP
    ] = MessageType.SUBAGENT_MESSAGE_RESP
    delivered: bool = True


# ============================================================================
# LIST
# ============================================================================
class SubagentListRequest(BaseMessage):
    type: Literal[
        MessageType.SUBAGENT_LIST_REQ
    ] = MessageType.SUBAGENT_LIST_REQ


class SubagentListResponse(BaseMessage):
    type: Literal[
        MessageType.SUBAGENT_LIST_RESP
    ] = MessageType.SUBAGENT_LIST_RESP

    subagents: List[SubagentInfo]


# ============================================================================
# CANCEL / TERMINATE
# ============================================================================
class SubagentCancelRequest(BaseMessage):
    type: Literal[
        MessageType.SUBAGENT_CANCEL_REQ
    ] = MessageType.SUBAGENT_CANCEL_REQ
    subagent_id: str


class SubagentTerminateRequest(BaseMessage):
    type: Literal[
        MessageType.SUBAGENT_TERMINATE_REQ
    ] = MessageType.SUBAGENT_TERMINATE_REQ
    subagent_id: str


# ============================================================================
# MERGE
# ============================================================================
class SubagentMergeRequest(BaseMessage):
    type: Literal[
        MessageType.SUBAGENT_MERGE_REQ
    ] = MessageType.SUBAGENT_MERGE_REQ

    subagent_ids: List[str]
    strategy: str = "hierarchical_summary"


class SubagentMergeResponse(BaseMessage):
    type: Literal[
        MessageType.SUBAGENT_MERGE_RESP
    ] = MessageType.SUBAGENT_MERGE_RESP
    merged_result: Dict[str, Any]


# ============================================================================
# EVENTS
# ============================================================================
class SubagentEvent(BaseMessage):
    type: Literal[
        MessageType.SUBAGENT_EVENT
    ] = MessageType.SUBAGENT_EVENT

    subagent_id: str
    event: str
    content: Dict[str, Any] = Field(default_factory=dict)
