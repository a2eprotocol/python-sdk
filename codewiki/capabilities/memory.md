# Memory

Memory gives agents persistence across turns and sessions. A2E defines three tiers — working (current-turn context), episodic (cross-session experience), and semantic (long-term knowledge) — so agents can remember what they just did, learn from past sessions, and recall learned facts, all through a single standard protocol.

## Overview

The **memory** capability provides a 3-tier memory system (working, episodic, semantic) with init, store, retrieve, and forget operations. Agents initialize a session to obtain a `memory_id`, then use it for all subsequent operations. Memory persists context across turns, recalls relevant information, and maintains knowledge bases.

## Memory Tiers

| Tier | Scope | Persistence | Use Case |
|------|-------|-------------|----------|
| `working` | Current session | In-memory, LRU eviction | Scratch pad, current task state |
| `episodic` | Per-agent | Across sessions | Conversation history, task episodes |
| `semantic` | Shared | Across agents | Shared knowledge base, facts |

## Protocol Messages (8 types)

| Type String | Model | Direction |
|-------------|-------|-----------|
| `memory/init/req` | `MemoryInitRequest` | Agent → Host |
| `memory/init/resp` | `MemoryInitResponse` | Host → Agent |
| `memory/store/req` | `MemoryStoreRequest` | Agent → Host |
| `memory/store/resp` | `MemoryStoreResponse` | Host → Agent |
| `memory/retrieve/req` | `MemoryRetrieveRequest` | Agent → Host |
| `memory/retrieve/resp` | `MemoryRetrieveResponse` | Host → Agent |
| `memory/forget/req` | `MemoryForgetRequest` | Agent → Host |
| `memory/forget/resp` | `MemoryForgetResponse` | Host → Agent |

### MemoryEntry

| Field | Type | Description |
|-------|------|-------------|
| `key` | `dict` | Structured key (hash or dict match) |
| `content` | `dict` | The stored value |
| `tier` | `MemoryTier` | `working`, `episodic`, or `semantic` |
| `tags` | `list[str]` | Classification tags for search |
| `source` | `str` | Who stored this entry |
| `score` | `float` | Relevance score |
| `ttl` | `float \| None` | Time-to-live in seconds |
| `timestamps` | `dict` | Created/updated/accessed timestamps |

### MemoryStoreRequest / Response

```python
# Request: batch store
MemoryStoreRequest(entries: list[MemoryEntry])

# Response: results
MemoryStoreResponse(stored: list, errors: list)
```

### MemoryRetrieveRequest / Response

```python
# Request: flexible retrieval
MemoryRetrieveRequest(
    keys=None,          # Exact key match
    query=None,         # Similarity search
    tags=None,          # Tag filter
    tier=None,          # Tier filter
    limit=10,           # Max results
    min_score=0.0       # Minimum relevance score
)

# Response
MemoryRetrieveResponse(entries: list[MemoryEntry], total: int)
```

### MemoryForgetRequest / Response

```python
# Request: delete by criteria
MemoryForgetRequest(keys=None, tags=None, tier=None)

# Response
MemoryForgetResponse(deleted: int)
```

## MemoryPlugin ABC

```python
class MemoryPlugin(A2EPlugin):
    @abstractmethod
    def on_init(self, namespace: str, scope: dict, metadata: Optional[dict] = None):
        """Returns (memory_id, backend_object) — allocates a new memory session"""

    @abstractmethod
    def on_store(self, memory, entries) -> tuple[list, list]:
        """Returns (stored_keys, errors)"""

    @abstractmethod
    def on_retrieve(self, req: MemoryRetrieveRequest) -> list[MemoryEntry]:
        """Returns matched entries"""

    @abstractmethod
    def on_forget(self, req: MemoryForgetRequest) -> int:
        """Returns count of deleted entries"""
```

## MemoryAPI (Client)

```python
from a2e.caps.memory.client import MemoryAPI

memory = MemoryAPI(client)

# Step 1: INIT — establish a memory session
resp = memory.init(namespace="my-agent", scope={"agent": "assistant"}, metadata={"version": "1.0"})
print(f"memory_id: {memory.memory_id}")

# Batch store
stored, errors = memory.store([
    MemoryEntry(key={"id": "fact1"}, content={"text": "Earth orbits the Sun"}, tier="semantic"),
    MemoryEntry(key={"id": "task1"}, content={"step": 3}, tier="working")
])

# Flexible retrieval
entries = memory.retrieve(
    query="solar system",   # Similarity search
    tier="semantic",
    limit=5,
    min_score=0.3
)

# Forget
deleted = memory.forget(tags=["temp"], tier="working")

# Convenience helpers
memory.remember("user_name", "Alice", tier="working", tags=["identity"])
name = memory.recall("user_name")  # Returns content or None
```

### Convenience Methods

| Method | Description |
|--------|-------------|
| `init(namespace, scope, metadata)` | Initialize a memory session — must be called first |
| `remember(key, value, tier, tags, ttl, score)` | Single key-value store |
| `recall(key, default=None)` | Single key retrieval |
