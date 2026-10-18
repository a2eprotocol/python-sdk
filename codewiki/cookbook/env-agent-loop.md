# Environment Agent Loop

A complete example of an agent interacting with an A2E environment in a standard RL loop.

## Full Example

```python
import logging
from a2e.schema import A2EHostConfig
from a2e.core.server.server import A2EServer
from a2e.core.client.client import A2EClient
from a2e.caps.env.client import EnvAPI
from a2e.caps.env.protocol import EnvAction

logger = logging.getLogger("agent")

# --- Server setup ---
config = A2EHostConfig.from_yaml("config.yaml")
server = A2EServer(config)

# For HTTP mode:
# app = server.start()
# uvicorn.run(app, host="0.0.0.0", port=8765)

# For direct mode (testing):
transport = server.start()

# --- Client setup ---
client = A2EClient(transport, logger, agent_id="rl-agent", agent_caps=["env", "tools"])
client.connect()

env = EnvAPI(client)

# --- RL Loop ---
def select_action(observation):
    """Simple policy: increment until we hit the target."""
    count = observation.state.get("count", 0)  # EnvState allows extra fields
    if count < 10:
        return EnvAction(action_type="inc", payload={"amount": 1})
    return EnvAction(action_type="dec", payload={"amount": 1})

# Reset environment
resp = env.reset(env_name="counter_env", seed=42)
episode_id = resp.episode_id
total_reward = 0.0
step = 0

print(f"Episode {episode_id} started. Initial state: {resp.observation.state}")

while True:
    action = select_action(resp.observation)
    resp = env.step(episode_id, action)
    total_reward += resp.observation.reward
    step += 1

    print(f"Step {step}: action={action.action_type}, "
          f"state={resp.observation.state.model_dump()}, "
          f"reward={resp.observation.reward:.2f}")

    if env.is_done(resp.observation.done, resp.observation.truncated):
        break

print(f"Episode finished! Total reward: {total_reward:.2f}, Steps: {step}")
env.close(episode_id)
client.disconnect()
```

## With Server Push

Some environments push state deltas without the agent requesting them:

```python
env = EnvAPI(client)

# Register push handler
env.on_push(lambda push: print(
    f"Push: event={push.event_type}, delta={push.delta}, "
    f"reward={push.reward}, terminal={push.terminal}"
))

# The push callback fires whenever the server sends env/state/push
```

Internally, `EnvAPI` registers a push handler via `client.register_push_handler("env/state/push", ...)` on construction. Pushes are delivered as unsolicited server-initiated messages, independent of any pending step/reset RPC.

## HTTP Mode Agent

For production use, the agent connects over HTTP:

```python
from a2e.core.transports.http import HTTPTransport

transport = HTTPTransport(config={"base_url": "http://localhost:8765"})
client = A2EClient(transport, logger, agent_caps=["env", "tools", "memory"])
client.connect()

# Same RL loop as above...
```

## Batch Step

For parallel environment interaction:

```python
# Multiple actions in one request
batch_resp = env.batch_step(episode_id, [
    EnvAction(action_type="inc", payload={"amount": 1}),
    EnvAction(action_type="inc", payload={"amount": 2}),
    EnvAction(action_type="dec", payload={"amount": 1}),
])
```

## Data Plane: Per-Task Data Staging

When many graded tasks share one long-lived environment, stage each task's data with the **data plane** instead of baking it into `on_reset`. `data_reset` restores the pristine baseline, `data_add` stages the task's inputs (metadata only — the host copies bytes locally), and `data_get` collects the agent's artifacts for grading. None of this touches the episode.

**Plugin side** — override the three optional hooks:

```python
import hashlib
import os
import shutil

from a2e.caps.env.plugin import EnvPlugin
from a2e.caps.env.protocol import DEFAULT_DATA_ROOT, EnvObservation, EnvState


class DataEnv(EnvPlugin):
    name = "env"
    type = "env"

    def __init__(self, host_instance=None, config=None):
        super().__init__(host_instance, config or {})
        self.baseline = (config or {}).get("baseline", [])  # [[src, name], ...]

    # ── episode hooks ──────────────────────────────────────────────
    def on_reset(self, seed=None, options=None):
        return EnvState(count=0, step_num=0, seed=seed or 0)

    def on_step(self, episode_id, action):
        ep = self._require_episode()
        n = int(ep.state.model_dump().get("count", 0)) + 1
        return EnvObservation(episode_id=episode_id, step_num=n,
                              state=EnvState(count=n, step_num=n),
                              reward=0.0, done=n >= 3)

    # ── data-plane hooks (optional; orthogonal to episodes) ────────
    def on_data_reset(self, scope="all", data_root=DEFAULT_DATA_ROOT):
        root = data_root or DEFAULT_DATA_ROOT
        if os.path.isdir(root):
            shutil.rmtree(root)
        os.makedirs(root, exist_ok=True)
        restored = 0
        for src, name in self.baseline:
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(root, name))
                restored += 1
        return {"restored": restored, "data_root": root, "detail": "pristine"}

    def on_data_add(self, parts, data_root=DEFAULT_DATA_ROOT):
        root = data_root or DEFAULT_DATA_ROOT
        os.makedirs(root, exist_ok=True)
        added, errors, staged = 0, [], []
        for p in parts:
            src, dest = p.get("src", ""), p.get("dest", "")
            target = os.path.join(root, dest or os.path.basename(src))
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(src, target)
                digest = hashlib.sha256(open(target, "rb").read()).hexdigest()
                want = (p.get("checksum") or "").replace("sha256:", "")
                if want and digest != want:
                    os.remove(target)
                    errors.append(f"checksum mismatch: {dest}")
                    continue
                added += 1
                staged.append({"uri": p.get("uri", ""), "dest": dest,
                               "size_bytes": os.path.getsize(target)})
            except Exception as exc:
                errors.append(f"{dest}: {exc}")
        return {"added": added, "errors": errors, "staged": staged, "data_root": root}

    def on_data_get(self, query="", include_content=False, max_bytes=1_048_576,
                    data_root=DEFAULT_DATA_ROOT):
        root = data_root or DEFAULT_DATA_ROOT
        items = []
        for dirpath, _, files in os.walk(root):
            for fn in files:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root)
                if query and query not in rel:
                    continue
                size = os.path.getsize(full)
                item = {"uri": rel, "dest": rel, "size_bytes": size}
                if include_content and size <= max_bytes:
                    item["content"] = open(full).read()
                items.append(item)
        return items
```

Register it with a baseline corpus (the pristine state `data_reset` restores):

```yaml
plugins:
  - name: env
    type: env
    cls: mypkg.env.DataEnv
    metadata:
      enabled: true
      baseline:                       # host-side [source, name] pairs
        - ["/srv/baseline/schema.sql", "schema.sql"]
```

**Client side** — the per-task cycle:

```python
env = EnvAPI(client)

for task in ("task-A", "task-B"):
    # 1. Restore pristine — drops the previous task's data AND its artifacts
    env.data_reset(scope="all")

    # 2. Stage this task's inputs — metadata only; the host copies bytes locally
    env.data_add(parts=[
        {"src": f"/srv/tasks/{task}/orders.csv", "dest": "orders.csv",
         "uri": "orders", "checksum": "sha256:..."},
    ])

    # 3. Run the episode (does NOT touch the data root)
    resp = env.reset(env_name="sql_task")
    episode_id = resp.episode_id
    while not env.is_done(resp.observation.done, resp.observation.truncated):
        resp = env.step(episode_id, select_action(resp.observation))
    env.close(episode_id)

    # 4. Collect the agent's artifacts for grading
    result = env.data_get(query=".csv", include_content=True, max_bytes=65536)
    print(task, [(i["uri"], i["size_bytes"]) for i in result.items])
```

**Why this shape.** Because `data_reset` restores *pristine* (not purge-to-empty), task B never sees task A's inputs or outputs, and the baseline corpus is always present. Because `data_add` carries metadata only, the same code stages a 2 KB CSV or a 20 GB dataset with no change and no wire blow-up.

### Data-plane patterns

| Pattern | API |
|---------|-----|
| Reset only the data root (leave the episode alone) | `env.data_reset(scope="all")` |
| Reset only the episode (leave the data alone) | `env.reset(env_name=...)` |
| Stage inputs cheaply (metadata only) | `env.data_add(parts=[...])` |
| Verify staged bytes | `EnvDataPart.checksum="sha256:<hex>"` |
| Collect small artifacts inline | `env.data_get(include_content=True, max_bytes=...)` |
| Enumerate large artifacts without inlining | `env.data_get(query=...)` |

> Byte-carrying is one-directional and opt-in: `data_add` never inlines content, and `data_get` inlines only when `include_content=True` and the item is within `max_bytes`. Everything else returns metadata.