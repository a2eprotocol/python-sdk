# Environment

The environment capability brings RL-native interaction patterns to A2E — reset, step, observe, reward — enabling agents to interact with simulators, games, browser automation, or any stateful system through a standard `env/step` loop. Rewards from env interactions feed directly into the learn capability for on-policy adaptation.

## Overview

The **env** capability provides a full RL environment interface — reset, step, observe, render, plan, and batch step. It follows the OpenAI Gym / PettingZoo paradigm, making A2E environments directly usable for reinforcement learning.

## Protocol Messages (25 types)

| Type String | Model | Direction |
|-------------|-------|-----------|
| `env/reset/req` | `EnvResetRequest` | Agent → Host |
| `env/reset/resp` | `EnvResetResponse` | Host → Agent |
| `env/step/req` | `EnvStepRequest` | Agent → Host |
| `env/step/resp` | `EnvStepResponse` | Host → Agent |
| `env/observe/req` | `EnvObserveRequest` | Agent → Host |
| `env/observe/resp` | `EnvObserveResponse` | Host → Agent |
| `env/close/req` | `EnvCloseRequest` | Agent → Host |
| `env/close/resp` | `EnvCloseResponse` | Host → Agent |
| `env/space/req` | `EnvSpacesRequest` | Agent → Host |
| `env/space/resp` | `EnvSpacesResponse` | Host → Agent |
| `env/render/req` | `EnvRenderRequest` | Agent → Host |
| `env/render/resp` | `EnvRenderResponse` | Host → Agent |
| `env/plan/req` | `EnvPlanRequest` | Agent → Host |
| `env/plan/resp` | `EnvPlanResponse` | Host → Agent |
| `env/batch_step/req` | `EnvBatchStepRequest` | Agent → Host |
| `env/batch_step/resp` | `EnvBatchStepResponse` | Host → Agent |
| `env/exp/list/req` | `EnvExpListRequest` | Agent → Host |
| `env/exp/list/resp` | `EnvExpListResponse` | Host → Agent |
| `env/state/push` | `EnvStatePush` | Host → Agent (server-initiated) |
| `env/data/reset/req` | `EnvDataResetRequest` | Agent → Host |
| `env/data/reset/resp` | `EnvDataResetResponse` | Host → Agent |
| `env/data/add/req` | `EnvDataAddRequest` | Agent → Host |
| `env/data/add/resp` | `EnvDataAddResponse` | Host → Agent |
| `env/data/get/req` | `EnvDataGetRequest` | Agent → Host |
| `env/data/get/resp` | `EnvDataGetResponse` | Host → Agent |

> The six `env/data/*` messages form a **data plane** that is orthogonal to the episode lifecycle. See [Data Plane](#data-plane) below.

### Core Models

**EnvAction** — What the agent does:
| Field | Type | Description |
|-------|------|-------------|
| `action_type` | `str` | Action identifier |
| `payload` | `dict` | Action parameters |
| `metadata` | `dict` | Extra context |

**EnvObservation** — What the agent sees:
| Field | Type | Description |
|-------|------|-------------|
| `episode_id` | `str` | Current episode |
| `step_num` | `int` | Step within episode |
| `state` | `EnvState` | Current environment state (flexible, `extra="allow"`) |
| `done` | `bool` | Episode terminated |
| `truncated` | `bool` | Episode truncated (time limit) |
| `reward` | `float` | Step reward |
| `metadata` | `dict` | Extra info |

**EnvStatePush** — Server-initiated state delta:
| Field | Type | Description |
|-------|------|-------------|
| `state_delta` | `dict` | Incremental state change |
| `reward` | `float` | Associated reward |
| `terminal` | `bool` | Whether environment terminated |
| `event_type` | `str` | Push event type |
| `reason` | `str` | Why this push occurred |

## EnvPlugin ABC

```python
class EnvPlugin(A2EPlugin):
    name = "base_env"

    @abstractmethod
    def on_reset(self, seed=None, options=None) -> EnvState:
        """Reset environment, return initial state"""

    @abstractmethod
    def on_step(self, episode_id: str, action: EnvAction) -> tuple:
        """Returns (next_state, reward, done, info)"""

    @abstractmethod
    def on_close(self): ...

    # Data plane (optional — default no-ops, NOT abstract; orthogonal to episodes)
    def on_data_reset(self, scope="all", data_root=DEFAULT_DATA_ROOT) -> dict: ...
    def on_data_add(self, parts, data_root=DEFAULT_DATA_ROOT) -> dict: ...
    def on_data_get(self, query="", include_content=False,
                    max_bytes=1_048_576, data_root=DEFAULT_DATA_ROOT) -> list: ...

    # Implemented methods
    def reset(self, msg) -> EnvResetResponse: ...
    def step(self, msg) -> EnvStepResponse: ...
    def observe(self, msg) -> EnvObserveResponse: ...
    def close(self, msg) -> EnvCloseResponse: ...
    def spaces(self, msg) -> EnvSpacesResponse: ...    # Action/state schemas
    def render(self, msg) -> EnvRenderResponse: ...    # Screenshot, RGB, text
    def plan(self, msg) -> EnvPlanResponse: ...         # Affordances

    # Push support
    def set_push_callback(self, cb): ...
    def push(self, episode_id, step_id, action_id, event_type, delta): ...
```

The `push()` helper emits an `EnvStatePush` event via the executor's `_send()` path. It now guards against missing episode state — `push()` returns early if no episode is active.

**Push event model**:
```python
EnvStatePush(
    episode_id=str,
    step_id=int,
    action_id=str,
    event_type=str,   # e.g. "observation", "reward", "termination"
    delta=dict,       # incremental state change
)
```

**Episode management**: The plugin tracks the current episode internally with `_episode` and `_store` (EpisodeStore). Episodes use a `default_factory` for UUID generation. Steps are persisted automatically.

## EnvAPI (Client)

```python
from a2e.caps.env.client import EnvAPI

env = EnvAPI(client)

# Reset environment
resp = env.reset(env_name="counter_env", seed=42, options={})
episode_id = resp.episode_id

# Step
resp = env.step(episode_id, EnvAction(action_type="inc", payload={}))
print(f"State: {resp.observation.state}, Reward: {resp.observation.reward}")

# Observe (without stepping)
obs = env.observe(episode_id)

# Check done
if env.is_done(resp.observation.done, resp.observation.truncated):
    print("Episode finished")

# Close
env.close(episode_id)

# Server-push support
env.on_push(lambda push: print(f"Push: {push.state_delta}"))
```

Under the hood, `EnvAPI.__init__()` calls `client.register_push_handler("env/state/push", self._on_push)` which routes incoming `EnvStatePush` messages to the registered callbacks. This decouples push handling from the RPC flow — pushes arrive as unsolicited server-initiated messages and are dispatched independently of any pending step/reset call.

### EpisodeStore

Persistence for episode state:

| Implementation | Backend | Schema |
|---------------|---------|--------|
| `SQLiteEpisodeStore` | SQLite | `episodes` table: `episode_id PK, env_name, state JSON, done, step_count, created_at, updated_at` |

## Data Plane

The env capability exposes a second, **episode-orthogonal** lifecycle for task data — the files an agent reads before a task and produces during it. Where `env/reset` starts a new *episode*, the three `env/data/*` operations move bytes into and out of the environment's **data root** (default `/workspace/data`):

| Operation | Request | Purpose |
|-----------|---------|---------|
| `env/data/reset` | `EnvDataResetRequest` | Restore the data root to its **pristine** state (clear + re-stage the baseline corpus) |
| `env/data/add` | `EnvDataAddRequest` | Stage task data into the data root before an episode |
| `env/data/get` | `EnvDataGetRequest` | Read items back out of the data root (graded artifact collection) |

The two lifecycles are deliberately independent: a host can reset an episode without touching data, and restore data without starting an episode. `data_reset` is **not** a purge-to-empty and **not** an episode reset — it restores whatever the host considers pristine (typically clearing the root and re-staging the env's baseline). A host with no baseline simply empties the root and reports `restored: 0`.

**Metadata only — bytes never cross the wire.** Payloads carry paths, checksums, and sizes; the host moves the actual bytes on its own filesystem (e.g. extracting a bind-mounted archive inside the container). This is what makes multi-GB corpora viable: a small request can stage a multi-GB dataset. `EnvDataPart.checksum` (`sha256:<hex>`) is verified host-side after staging.

```python
# Between tasks: drop the previous task's data, restore the baseline
env.data_reset(scope="all")                    # -> EnvDataResetResponse(restored=N)

# Stage task data (metadata only — the host copies bytes locally)
env.data_add(parts=[
    {"src": "/host/tasks/task-B/orders.csv", "dest": "orders.csv",
     "uri": "orders", "checksum": "sha256:..."},
    {"src": "/host/tasks/task-B/corpus.tar", "dest": "corpus/"},
])

# Run the episode (env/reset — does NOT touch the data root)
ep = env.reset(env_name="sql_task")

# Collect the agent's artifacts (graded output)
result = env.data_get(query="*.csv", include_content=True, max_bytes=65536)
for item in result.items:
    print(item["uri"], item["size_bytes"], item.get("content"))
```

**Failure semantics.** `data_add` is per-part resilient: a bad part is reported in `errors[]` and never aborts the batch; `ok` is `False` only when the batch produced errors. `data_get` inlines file `content` only when the caller sets `include_content=True` *and* the item is within `max_bytes` (default 1 MiB) — the host must refuse to inline anything larger, and `truncated` flags the case where an inlined item hit the cap. Without `include_content`, every matching item is returned as metadata.

### EnvDataPart

| Field | Type | Description |
|-------|------|-------------|
| `src` | `str` | Host-side source path the host copies from |
| `dest` | `str` | Destination path relative to the data root (empty ⇒ the source's basename) |
| `uri` | `str` | Logical identifier, recorded and echoed back (not dereferenced by the SDK) |
| `checksum` | `str` | `sha256:<hex>`, verified host-side after staging (empty skips verification) |
| `size_bytes` | `int` | Size of the staged item |
| `mime` | `str` | Optional MIME type |

## RL Loop Pattern

```python
env = EnvAPI(client)
resp = env.reset(env_name="my_env")
episode_id = resp.episode_id

while True:
    action = select_action(resp.observation)  # Your policy
    resp = env.step(episode_id, action)
    if env.is_done(resp.observation.done, resp.observation.truncated):
        break
env.close(episode_id)
```
