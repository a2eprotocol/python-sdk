# ═════════════════════════════════════════════════════════════════════════════
# ── NAMESPACE: memory/*  ─────────────────────────────────────────────────────
#
# The agent's episodic + semantic memory store.
# Memories are key-value blobs with optional vector embeddings for similarity
# search.  The host decides the backend (SQLite, Redis, Chroma, …).
#
# Three memory tiers:
#   working   — in-session, lost on disconnect
#   episodic  — persisted per-agent across sessions
#   semantic  — shared across all agents (collective knowledge)
# ═════════════════════════════════════════════════════════════════════════════
import time
from enum import Enum
from typing import Any, Dict, List
from pydantic import BaseModel, Field
from a2e.caps.base.protocol import A2EMessage


class MessageType(str, Enum):
    MEMORY_INIT_REQ = "memory/init/req"
    MEMORY_INIT_RESP = "memory/init/resp"
    MEMORY_STORE_REQ = "memory/store/req"
    MEMORY_STORE_RESP = "memory/store/resp"
    MEMORY_RETRIEVE_REQ = "memory/retrieve/req"
    MEMORY_RETRIEVE_RESP = "memory/retrieve/resp"
    MEMORY_FORGET_REQ = "memory/forget/req"
    MEMORY_FORGET_RESP = "memory/forget/resp"


class MemoryErrorCode(str, Enum):
    MEMORY_FULL = "memory_full"
    MEMORY_NOT_FOUND = "memory_not_found"


class MemoryTier(str, Enum):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"


class MemoryEntry(BaseModel):
    key: Dict
    content: Any           # JSON-serialisable
    tier: str
    tags: list[str] = Field(default_factory=list)
    source: str = ""   # e.g. "turn-42", "skill:text_summarizer"
    score: float = 1.0  # relevance / importance weight
    ttl: int = 0    # seconds; 0 = no expiry
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


# ============================================================
# Protocol Messages
# ============================================================
class MemoryInitRequest(A2EMessage):
    type: MessageType = MessageType.MEMORY_INIT_REQ
    namespace: str = "default"
    scope: dict[str, str] = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


class MemoryInitResponse(A2EMessage):
    type: MessageType = MessageType.MEMORY_INIT_RESP
    req_id: str = ""
    memory_id: str
    namespace: str
    success: bool = True


class MemoryStoreRequest(A2EMessage):
    """Agent → Host.  Write one or more memory entries."""
    type: MessageType = MessageType.MEMORY_STORE_REQ
    memory_id: str
    entries: list[dict] = Field(default_factory=list)   # list[MemoryEntry]


class MemoryStoreResponse(A2EMessage):
    type: MessageType = MessageType.MEMORY_STORE_RESP
    req_id: str = ""
    stored: List[Dict] = Field(default_factory=list)   # keys that were written
    errors: list[str] = Field(default_factory=list)


class MemoryRetrieveRequest(A2EMessage):
    """
    Agent → Host.  Retrieve memory entries.

    Supply `keys` for exact lookup, or `query` for similarity search,
    or `tags` to filter by tag.  All Fields are ANDed when multiple are set.
    """
    memory_id: str
    type: MessageType = MessageType.MEMORY_RETRIEVE_REQ
    
    keys: List[Dict] = Field(default_factory=list)
    query: str = ""       # semantic similarity search
    tags: list[str] = Field(default_factory=list)
    tier: str = ""       # empty = search all tiers
    limit: int = 10
    min_score: float = 0.0


class MemoryRetrieveResponse(A2EMessage):
    type: MessageType = MessageType.MEMORY_RETRIEVE_RESP
    req_id: str = ""
    entries: list[dict] = Field(default_factory=list)   # list[MemoryEntry]
    total: int = 0


class MemoryForgetRequest(A2EMessage):
    """Agent → Host.  Delete memory entries by key or tag."""
    memory_id: str
    type: MessageType = MessageType.MEMORY_FORGET_REQ
    keys: List[Dict] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    tier: str = MemoryTier.EPISODIC.value


class MemoryForgetResponse(A2EMessage):
    type: MessageType = MessageType.MEMORY_FORGET_RESP
    req_id: str = ""
    deleted: int = 0


# Memory message types are also valid in A2E
MEMORY_TYPE_MAP = {
    MessageType.MEMORY_INIT_REQ: MemoryInitRequest,
    MessageType.MEMORY_INIT_RESP: MemoryInitResponse,
    MessageType.MEMORY_STORE_REQ: MemoryStoreRequest,
    MessageType.MEMORY_STORE_RESP: MemoryStoreResponse,
    MessageType.MEMORY_RETRIEVE_REQ: MemoryRetrieveRequest,
    MessageType.MEMORY_RETRIEVE_RESP: MemoryRetrieveResponse,
    MessageType.MEMORY_FORGET_REQ: MemoryForgetRequest,
    MessageType.MEMORY_FORGET_RESP: MemoryForgetResponse,
}
