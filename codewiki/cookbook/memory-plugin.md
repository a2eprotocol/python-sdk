# Memory Plugin & Client Example

## Overview

This cookbook walks through building a custom memory backend (plugin side) and consuming it from an agent (client side). The memory capability provides a 3-tier store — working, episodic, semantic — with init, store, retrieve, and forget operations.

### Protocol Flow

```
Agent                    Host
  |                        |
  |-- memory/init/req ---->|
  |   namespace, scope,    |
  |   metadata             |
  |                        |  (allocates backend session)
  |<-- memory/init/resp ---|
  |   memory_id, namespace |
  |                        |
  |-- memory/store/req --->|
  |   memory_id, entries[] |
  |<-- memory/store/resp --|
  |                        |
  |-- memory/retrieve/req ->|
  |   memory_id, tags,     |
  |   tier, limit          |
  |<-- memory/retrieve/resp |
  |   entries[]            |
  |                        |
  |-- memory/forget/req --->|
  |   memory_id, tags,     |
  |   tier                 |
  |<-- memory/forget/resp --|
  |   deleted              |
```

Every `store`/`retrieve`/`forget` request carries the `memory_id` returned from `init`. The host uses it to route operations to the correct backend session.

## Plugin Side: SQLite Memory Backend

The `MemoryPlugin` ABC requires four methods: `on_init`, `on_store`, `on_retrieve`, and `on_forget`. Below is a complete SQLite-backed implementation.

```python
import json
import sqlite3
import time
import uuid
from typing import Optional
from a2e.caps.memory import (
    MemoryPlugin,
    MemoryEntry,
)

class SQLiteMemoryPlugin(MemoryPlugin):
    """SQLite-backed memory plugin with full CRUD and tag filtering."""

    name = "sqlite_memory"
    type = "memory"
    priority = 0

    def __init__(self, host_instance, config):
        super().__init__(host_instance, config)
        db_path = config.get("db_path", ":memory:")
        self._db = sqlite3.connect(db_path)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS memory (
                memory_id TEXT NOT NULL,
                key_json  TEXT NOT NULL,
                content   TEXT NOT NULL,
                tier      TEXT NOT NULL,
                tags_json TEXT NOT NULL DEFAULT '[]',
                source    TEXT NOT NULL DEFAULT '',
                score     REAL NOT NULL DEFAULT 1.0,
                ttl       REAL NOT NULL DEFAULT 0,
                created_at REAL NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL DEFAULT 0
            )
        """)
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_id ON memory(memory_id)"
        )
        self._db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_mem_key_tier "
            "ON memory(memory_id, key_json, tier)"
        )
        self._db.commit()

    # --- Required: Abstract Hook Implementations ---

    def on_init(
        self,
        namespace: str,
        scope: dict,
        metadata: Optional[dict] = None,
    ):
        """Create a new memory session and return (memory_id, backend_object).

        The memory_id is passed back in every subsequent request so the
        host can route operations to this session.
        """
        memory_id = str(uuid.uuid4())
        # The backend object is self — the single SQLite DB handles all
        # sessions, differentiated by the memory_id column.
        return memory_id, self

    def on_store(
        self,
        memory,
        entries: list[MemoryEntry],
    ) -> tuple[list, list]:
        stored_keys = []
        errors = []
        now = time.time()

        for entry in entries:
            try:
                key_json = json.dumps(entry.key, sort_keys=True)
                content_json = json.dumps(entry.content)
                tags_json = json.dumps(entry.tags)
                tier = entry.tier
                ttl = entry.ttl or 0

                self._db.execute(
                    """INSERT INTO memory
                       (memory_id, key_json, content, tier, tags_json,
                        source, score, ttl, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(memory_id, key_json, tier) DO UPDATE SET
                         content=excluded.content,
                         tags_json=excluded.tags_json,
                         source=excluded.source,
                         score=excluded.score,
                         ttl=excluded.ttl,
                         updated_at=excluded.updated_at
                    """,
                    (memory, key_json, content_json, tier, tags_json,
                     entry.source, entry.score, ttl, now, now)
                )
                self._db.commit()
                stored_keys.append(entry.key)
            except Exception as exc:
                errors.append(str(exc))

        return stored_keys, errors

    def on_retrieve(
        self,
        memory,
        req,
    ) -> list[MemoryEntry]:
        query_parts = ["SELECT * FROM memory WHERE memory_id = ?"]
        params = [memory]

        # Filter by tier
        if req.tier:
            query_parts.append("AND tier = ?")
            params.append(req.tier)

        # Filter by exact keys
        if req.keys:
            key_patterns = [json.dumps(k, sort_keys=True) for k in req.keys]
            placeholders = ",".join("?" * len(key_patterns))
            query_parts.append(f"AND key_json IN ({placeholders})")
            params.extend(key_patterns)

        # Filter by tags (JSON array overlap via subquery)
        if req.tags:
            for tag in req.tags:
                query_parts.append("AND tags_json LIKE ?")
                params.append(f'%"{tag}"%')

        # Apply TTL expiry filter (0 = no expiry)
        query_parts.append("AND (ttl = 0 OR created_at + ttl > ?)")
        params.append(time.time())

        # Apply min_score
        if req.min_score and req.min_score > 0:
            query_parts.append("AND score >= ?")
            params.append(req.min_score)

        # Order by score descending, apply limit
        query_parts.append("ORDER BY score DESC LIMIT ?")
        params.append(req.limit or 10)

        rows = self._db.execute(" ".join(query_parts), params).fetchall()

        entries = []
        for row in rows:
            (
                memory_id, key_json, content_json, tier, tags_json,
                source, score, ttl, created_at, updated_at,
            ) = row
            entries.append(MemoryEntry(
                key=json.loads(key_json),
                content=json.loads(content_json),
                tier=tier,
                tags=json.loads(tags_json),
                source=source,
                score=score,
                ttl=ttl,
                created_at=created_at,
                updated_at=updated_at,
            ))

        return entries

    def on_forget(
        self,
        memory,
        req,
    ) -> int:
        query_parts = ["DELETE FROM memory WHERE memory_id = ?"]
        params = [memory]

        if req.tier:
            query_parts.append("AND tier = ?")
            params.append(req.tier)

        if req.keys:
            key_patterns = [json.dumps(k, sort_keys=True) for k in req.keys]
            placeholders = ",".join("?" * len(key_patterns))
            query_parts.append(f"AND key_json IN ({placeholders})")
            params.extend(key_patterns)

        if req.tags:
            for tag in req.tags:
                query_parts.append("AND tags_json LIKE ?")
                params.append(f'%"{tag}"%')

        cursor = self._db.execute(" ".join(query_parts), params)
        self._db.commit()
        return cursor.rowcount

    # --- Lifecycle ---

    def teardown(self):
        if hasattr(self, "_db"):
            self._db.close()

    # --- State persistence ---

    def save_state(self, store, key, session_id):
        if self._db.execute("SELECT COUNT(*) FROM memory").fetchone()[0] > 0:
            rows = self._db.execute("SELECT * FROM memory").fetchall()
            store.save(f"{self.name}:{key}", {"rows": rows})

    def restore_state(self, store, key, session_id):
        state = store.load(f"{self.name}:{key}")
        if state and "rows" in state:
            for row in state["rows"]:
                self._db.execute(
                    "INSERT OR REPLACE INTO memory VALUES (?,?,?,?,?,?,?,?,?,?)",
                    row
                )
            self._db.commit()

    def clear_state(self, store, key, session_id):
        self._db.execute("DELETE FROM memory")
        self._db.commit()
        store.clear(f"{self.name}:{key}")
```

Key changes from the old pattern:

| Before | After | Why |
|--------|-------|-----|
| `A2EPlugin` base class | `MemoryPlugin` base class | Base class handles message routing |
| `supported_messages()` + `handle()` | Only abstract hooks | Routing is automatic |
| No init step | `on_init()` returns `(memory_id, backend)` | Required by new protocol |
| `on_store(entries)` | `on_store(memory, entries)` | `memory` is the backend object |
| Plain `key` in `on_store` | `memory_id` column in SQL | Multi-session isolation |

### Register in Config

```yaml
plugins:
  - name: sqlite_memory
    type: memory
    cls: my_package.memory.SQLiteMemoryPlugin
    metadata:
      db_path: /var/lib/a2e/memory.db
      enabled: true
      priority: 0
```

## Client Side: Agent Memory Usage

The `MemoryAPI` client provides both batch operations and convenience helpers. The init step must be called first to obtain a `memory_id`.

```python
import logging
from a2e.schema import A2EHostConfig
from a2e.core.server.server import A2EServer
from a2e.core.client.client import A2EClient
from a2e.caps.memory.client import MemoryAPI
from a2e.caps.memory.protocol import MemoryEntry

logger = logging.getLogger("memory-agent")

# --- Setup ---
config = A2EHostConfig.from_yaml("config.yaml")
server = A2EServer(config)
transport = server.start()

client = A2EClient(transport, logger, agent_caps=["memory"])
client.connect()

memory = MemoryAPI(client)

# ============================================================
# 0. INIT — establish a memory session
# ============================================================
resp = memory.init(
    namespace="agent-session-1",
    scope={"agent": "assistant"},
    metadata={"version": "1.0"},
)
print(f"Session established: memory_id={memory.memory_id}")

# ============================================================
# 1. Simple key-value usage with convenience helpers
# ============================================================

# Store a single fact
memory.remember(
    "user_name",
    "Alice",
    tier="working",
    tags=["identity"],
    score=0.9
)

# Recall it later
name = memory.recall("user_name")
print(f"User name: {name}")  # "Alice"

# ============================================================
# 2. Batch store with structured keys
# ============================================================

stored, errors = memory.store([
    MemoryEntry(
        key={"agent": "assistant", "topic": "preferences"},
        content={"language": "python", "style": "concise"},
        tier="episodic",
        tags=["preferences", "coding"],
        source="turn-1",
        score=0.9,
    ),
    MemoryEntry(
        key={"agent": "assistant", "topic": "task_state"},
        content={"step": 3, "total": 10, "status": "in_progress"},
        tier="working",
        tags=["task", "progress"],
        source="skill:planner",
        score=0.7,
    ),
    MemoryEntry(
        key={"topic": "fact", "id": "earth_orbit"},
        content={"text": "Earth orbits the Sun in 365.25 days"},
        tier="semantic",
        tags=["astronomy", "science"],
        source="turn-5",
        score=0.95,
    ),
])

print(f"Stored: {len(stored)} entries, Errors: {len(errors)}")

# ============================================================
# 3. Retrieval by key, tags, and tier
# ============================================================

# Exact key lookup
entries = memory.retrieve(
    keys=[{"agent": "assistant", "topic": "preferences"}],
    tier="episodic",
)
for entry in entries:
    print(f"Key: {entry.key} -> {entry.content}")

# Tag-based search
task_entries = memory.retrieve(
    tags=["task"],
    tier="working",
    limit=5,
)
for entry in task_entries:
    print(f"Task state: {entry.content}")

# Cross-tier search by tags
science = memory.retrieve(
    tags=["science"],
    limit=10,
    min_score=0.8,
)
for entry in science:
    print(f"[{entry.tier}] {entry.content}")

# ============================================================
# 4. TTL-based temporary memory
# ============================================================

# Store with 60-second TTL (auto-expires after 1 minute)
memory.store([
    MemoryEntry(
        key={"id": "temp_cache"},
        content={"data": "temporary value"},
        tier="working",
        tags=["temp"],
        ttl=60,  # seconds
    )
])

# ============================================================
# 5. Forgetting (deletion)
# ============================================================

# Forget by tags + tier (cleanup temp working memory)
deleted = memory.forget(tags=["temp"], tier="working")
print(f"Deleted {deleted} temp entries")

# Forget specific keys
deleted = memory.forget(
    keys=[{"agent": "assistant", "topic": "task_state"}],
    tier="working",
)
print(f"Deleted {deleted} specific entries")

# Forget all working memory
deleted = memory.forget(tier="working")
print(f"Cleared {deleted} working memory entries")

# ============================================================
# 6. Agent loop with memory-augmented context
# ============================================================

def process_user_turn(user_input: str):
    # Recall relevant context
    context = memory.retrieve(
        query=user_input,  # Similarity search (if backend supports it)
        tier="episodic",
        limit=3,
        min_score=0.5,
    )

    # Build prompt with memory context
    memory_text = "\n".join(
        f"- {e.content}" for e in context
    )
    prompt = f"Past context:\n{memory_text}\n\nUser: {user_input}"

    # ... generate response using LLM ...

    response_text = f"Response to: {user_input}"

    # Store this turn in episodic memory
    memory.store([
        MemoryEntry(
            key={"topic": "conversation", "turn": user_input[:50]},
            content={"user": user_input, "assistant": response_text},
            tier="episodic",
            tags=["conversation"],
            source="turn-latest",
            score=0.6,
        )
    ])

    return response_text

client.disconnect()
```

## Key Patterns

| Pattern | Tier | When to Use |
|---------|------|-------------|
| `init(namespace, scope)` | — | First call — establishes backend session |
| `remember(key, value)` | working | Quick scratch-pad in current session |
| `store([MemoryEntry])` | any | Batch writes with full metadata |
| `retrieve(keys=...)` | any | Exact key lookup |
| `retrieve(tags=...)` | any | Category-based search |
| `retrieve(query=...)` | episodic/semantic | Semantic similarity search |
| `recall(key)` | working | Single-value convenience helper |
| `forget(tags=..., tier=...)` | any | Bulk cleanup by category |

## Tips

- **Always call `init()` first**: It allocates the backend session and returns a `memory_id`. All subsequent operations use it.
- **Use structured keys**: `{"agent": "a1", "topic": "prefs"}` is more queryable than flat strings.
- **Tag aggressively**: Tags are the primary filter mechanism. Add multiple per entry.
- **Working tier is free**: No persistence cost, use it for current-task state.
- **Set TTL on temporary data**: Avoids manual cleanup; the host garbage-collects expired entries.
- **Batch store for efficiency**: `store([entry1, entry2, ...])` is one round-trip instead of N.
- **Score helps ranking**: Higher-scored entries are returned first in retrieval results.