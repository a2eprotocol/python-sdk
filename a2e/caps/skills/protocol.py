"""
skills/protocol.py — Skill Communication Protocol (Skill)

Defines every message that flows between the agent and a skill host.
Inspired by MCP / JSON-RPC 2.0; optimised for sandboxed, multi-turn
agentic loops where skills live in Docker containers.

Wire format
───────────
Each message is a newline-delimited JSON object (NDJSON).  The host and
agent communicate over stdin/stdout (or a named UNIX socket for IPC).

Message shape:

  { "skills": "1.0", "id": "<uuid>", "type": "<MessageType>", ...fields }

All fields described below are required unless marked Optional.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Optional, Dict, List
from pydantic import BaseModel, Field
from a2e.caps.base.protocol import (
    A2EMessage,
    A2EEvent,
)
#from a2e.tools.protocol import (
#    ToolDefinition
#)

#from a2e.toolkits.protocol import (
#    ToolkitDefinition
#)


# LLM Configuration
class LLMConfig(BaseModel):
    provider_name: str
    provider_credentials: Dict
    provider_config: Optional[Dict] = False
    is_default: Optional[bool] = False


class SkillErrorCode(str, Enum):
    UNKNOWN_SKILL = "unknown_skill"
    SKILL_ERROR = "skill_error"
    RUNTIME_ERROR = "runtime_error"


class SkillStatus(str, Enum):
    Created = "Created"
    Blocked = "Blocked"
    Published = "Published"
    Archived = "Archived"


# ═════════════════════════════════════════════════════════════════════════════
# Enumerations
# ═════════════════════════════════════════════════════════════════════════════
class MessageType(str, Enum):
    # Discovery
    SKILL_DISCOVER_REQ = "skill/discover/req"
    SKILL_DISCOVER_RESP = "skill/discover/resp"
    SKILL_CALL_REQ = "skill/call/req"
    SKILL_CALL_RESP = "skill/call/resp"
    SKILL_EVENT = "skill/event"
    ERROR = "error"


class ErrorCode(str, Enum):
    # Protocol-level
    PARSE_ERROR = "parse_error"
    INVALID_MESSAGE = "invalid_message"
    UNKNOWN_SKILL = "unknown_skill"
    VERSION_MISMATCH = "version_mismatch"
    UNAUTHORIZED = "unauthorized"

    # Execution-level
    SCHEMA_VIOLATION = "schema_violation"   # input didn't match skill schema
    TIMEOUT = "timeout"
    OOM = "out_of_memory"
    SANDBOX_CRASH = "sandbox_crash"
    SKILL_ERROR = "skill_error"        # skill itself returned non-zero


# ---------------------------------------------------------------------------
# SkillDefinition
# ---------------------------------------------------------------------------
class SkillDefinition(BaseModel):
    """
    Public contract for a skill.

    This is what the agent sees via discover.
    """

    # ─────────────────────────────
    # Identity
    # ─────────────────────────────
    name: str
    version: str
    description: str
    triggers: List[str]
    tools: Optional[List[Any]] = None  # List of tools
    toolkits: Optional[List[Any]] = None  # List of Toolkit
    status: SkillStatus

    # ─────────────────────────────
    # Interaction contract
    # ─────────────────────────────
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)

    # Natural language instruction (VERY important for agents)
    instructions: Optional[str] = None
    file_path: Optional[str] = None
    llm_config: Optional[LLMConfig] = None
    arguments: Optional[List[str]] = {}

    # ─────────────────────────────
    # When to use
    # ─────────────────────────────
    when_to_use: str
    argument_hint: str
    source: str  # user vs system vs project

    # ─────────────────────────────
    # Classification
    # ─────────────────────────────
    category: Optional[str] = None
    tags: Optional[List[str]] = None

    # ─────────────────────────────
    # Runtime hints
    # ─────────────────────────────
    max_turns: Optional[int] = None
    timeout_seconds: Optional[int] = None

    # ─────────────────────────────
    # UX / display
    # ─────────────────────────────
    icon: Optional[str] = None

    # ─────────────────────────────
    # Metadata
    # ─────────────────────────────
    metadata: Optional[dict] = None

    model_config = {
        "extra": "ignore"
    }


# ═════════════════════════════════════════════════════════════════════════════
# Discovery
# ═════════════════════════════════════════════════════════════════════════════
class SkillDiscoverRequest(A2EMessage):
    """
    Agent → Host.  "What skills are you serving?"

    `filter_tags` narrows results; empty = return all.
    """
    type: MessageType = MessageType.SKILL_DISCOVER_REQ
    filter_tags: list[str] = Field(default_factory=list)
    filter_categories: list[str] = Field(default_factory=list)


class SkillDiscoverResponse(A2EMessage):
    """Host → Agent.  Returns all available skill manifests."""
    type: MessageType = MessageType.SKILL_DISCOVER_RESP
    req_id: str = ""
    skills: list[SkillDefinition] = Field(default_factory=list)


class SkillCallRequest(A2EMessage):
    """
    Agent → Host. Execute a skill.

    `name`      — must match SkillDefinition.name
    `input`         — validated against skill.input_schema
    `session_id`    — same session as tools/env
    `correlation_id`— ties to agent turn / trajectory
    """

    type: MessageType = MessageType.SKILL_CALL_REQ

    name: str = ""
    arguments: Dict[str, Any] = Field(default_factory=dict)

    correlation_id: str = ""

    # Execution control
    timeout: int = 60
    streaming: bool = True

    # Optional overrides
    llm_override: Optional[LLMConfig] = None

    # allows agent to override model / temp / etc.
    metadata: dict = Field(default_factory=dict)


class SkillEvent(A2EEvent):
    """
    Host → Agent. Streaming events during skill execution.
    """

    type: MessageType = MessageType.SKILL_EVENT


class SkillResult(BaseModel):
    success: bool

    data: Optional[Any] = None
    summary: Optional[Any] = None
    truncated: Optional[bool] = False

    error: Optional[str] = None
    error_code: Optional[str] = None

    duration_ms: int

    events: List["SkillEvent"] = Field(default_factory=list)

    def raise_for_error(self) -> "SkillResult":
        if not self.success:
            raise RuntimeError(
                f"Skill {self.skill_id} failed [{self.error_code}]: {self.error}"
            )
        return self


class SkillCallResponse(A2EMessage):
    """
    Host → Agent. Final result of skill execution.
    """

    type: MessageType = MessageType.SKILL_CALL_RESP

    req_id: str = ""
    name: str = ""

    data: Optional[SkillResult]

    # Transport-level error (only if protocol failed)
    error: Optional[dict] = None

    # { code, message, retryable }
    created_at: float = Field(default_factory=time.time)


SKILL_TYPE_MAP = {
    MessageType.SKILL_DISCOVER_REQ: SkillDiscoverRequest,
    MessageType.SKILL_DISCOVER_RESP: SkillDiscoverResponse,
    MessageType.SKILL_CALL_REQ: SkillCallRequest,
    MessageType.SKILL_CALL_RESP: SkillCallResponse,
    MessageType.SKILL_EVENT: SkillEvent,
}
