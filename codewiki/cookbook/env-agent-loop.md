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
    f"Push: delta={push.state_delta}, reward={push.reward}, "
    f"terminal={push.terminal}, reason={push.reason}"
))

# The push callback fires whenever the server sends env/state_push
```

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