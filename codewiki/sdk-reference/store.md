# Persistence (Store)

## Overview

A2E environments are **stateful by design**. The `SnapshotStore` abstraction provides a simple key-value persistence interface used by the host and plugins for snapshot/restore operations.

## SnapshotStore ABC

```python
class SnapshotStore(ABC):
    @abstractmethod
    def save(self, key: str, state: dict): ...

    @abstractmethod
    def load(self, key: str) -> dict: ...

    @abstractmethod
    def delete(self, key: str): ...
```

A pure dict-based interface. Keys are strings, values are dicts (serialized to JSON internally).

## FileSnapshotStore

Stores each key as `<key>.json` in a root directory.

```python
from a2e.core.store.file import FileSnapshotStore

store = FileSnapshotStore(root="/tmp/a2e-snapshots")
store.save("session_abc", {"step": 5, "done": False})
state = store.load("session_abc")  # {"step": 5, "done": False}
store.delete("session_abc")
```

**Implementation details**:
- Auto-creates root directory on first write
- Uses `json.dump()` / `json.load()` for serialization
- `delete()` uses `unlink(missing_ok=True)` — no error if key doesn't exist

## SQLiteSnapshotStore

SQLite-backed persistence with a `snapshots` table.

```python
from a2e.core.store.db import SQLiteSnapshotStore

store = SQLiteSnapshotStore(db_path="/data/a2e.db")
store.save("session_abc", {"step": 5, "done": False})
state = store.load("session_abc")
```

**Schema**:
```sql
CREATE TABLE IF NOT EXISTS snapshots (
    key TEXT PRIMARY KEY,
    state TEXT  -- JSON-serialized dict
)
```

**Implementation details**:
- `save()` uses `REPLACE INTO` (upsert semantics)
- `load()` raises `KeyError` if key not found
- `delete()` removes the row

## SnapshotStoreConfig

```yaml
snapshot_store:
  type: file         # "file", "sqlite", or "custom"
  config:
    root: "/tmp/a2e-snapshots"  # For "file" type
    # db_path: "/data/a2e.db"   # For "sqlite" type
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | `str` | `"file"` | Store backend type |
| `config` | `dict` | `{}` | Backend-specific configuration |

## Plugin Integration

Plugins use `save_state()` / `restore_state()` / `clear_state()` to persist their state across sessions:

```python
# In A2EPlugin
def save_state(self, store: SnapshotStore, key: str, session_id: str):
    state = {"my_data": self._data}
    store.save(f"{self.name}:{key}", state)

def restore_state(self, store: SnapshotStore, key: str, session_id: str):
    state = store.load(f"{self.name}:{key}")
    self._data = state.get("my_data", {})
```

The key is namespaced as `"plugin_name:key"` to avoid collisions between plugins.

## Snapshot Modes

The `snapshot_mode` in `A2EHostConfig` controls who triggers snapshots:

| Mode | Description |
|------|-------------|
| `"host"` | Host-level snapshots only (full environment state) |
| `"plugin"` | Each plugin manages its own snapshots independently |
| `"hybrid"` | Both host and plugin-level snapshots (recommended) |

## Use Cases

- **Checkpoint/restore**: Save environment state at a point in time, restore later
- **Replay**: Replay agent interactions from saved state
- **RL training**: Branch environment states for parallel exploration
- **Crash recovery**: Resume from last snapshot after host restart
