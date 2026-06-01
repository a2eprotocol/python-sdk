# Environment

The environment capability brings RL-native interaction patterns to A2E — reset, step, observe, reward — enabling agents to interact with simulators, games, browser automation, or any stateful system through a standard `env/step` loop. Rewards from env interactions feed directly into the learn capability for on-policy adaptation.

## Overview

The **env** capability provides a full RL environment interface — reset, step, observe, render, plan, and batch step. It follows the OpenAI Gym / PettingZoo paradigm, making A2E environments directly usable for reinforcement learning.

## Protocol Messages (14 types)

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
| `env/spaces/req` | `EnvSpacesRequest` | Agent → Host |
| `env/spaces/resp` | `EnvSpacesResponse` | Host → Agent |
| `env/render/req` | `EnvRenderRequest` | Agent → Host |
| `env/render/resp` | `EnvRenderResponse` | Host → Agent |
| `env/plan/req` | `EnvPlanRequest` | Agent → Host |
| `env/plan/resp` | `EnvPlanResponse` | Host → Agent |
| `env/batch_step/req` | `EnvBatchStepRequest` | Agent → Host |
| `env/batch_step/resp` | `EnvBatchStepResponse` | Host → Agent |
| `env/state_push` | `EnvStatePush` | Host → Agent (server-initiated) |

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

Under the hood, `EnvAPI.__init__()` calls `client.register_push_handler("env/state_push", self._on_push)` which routes incoming `EnvStatePush` messages to the registered callbacks. This decouples push handling from the RPC flow — pushes arrive as unsolicited server-initiated messages and are dispatched independently of any pending step/reset call.

### EpisodeStore

Persistence for episode state:

| Implementation | Backend | Schema |
|---------------|---------|--------|
| `SQLiteEpisodeStore` | SQLite | `episodes` table: `episode_id PK, env_name, state JSON, done, step_count, created_at, updated_at` |

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
