---
title: "Building an A2E-Integrated Agent and Harness"
date: 2026-09-09
authors: ["A2E Protocol Team"]
tags: ["a2e", "tutorial", "agent", "harness", "rl", "env", "protocol", "plugin"]
summary: "A practical walkthrough of building a realistic agent that talks to an A2E environment, complete with environment plugin, host adapter, RL loop, and learning feedback — grounded in the SDK's cookbook examples."
---

# Building an A2E-Integrated Agent and Harness

From the ground up — environment plugin, host adapter, RL loop, and learning feedback.

---

**A2E (Agent-to-Environment)** is an open protocol and Python SDK that standardizes how AI agents interact with their environment — tools, memory, processes, subagents, feedback loops, and RL environments. This post walks through building a realistic agent and harness on top of the A2E protocol, using the Python SDK's cookbook as our guide.

If you haven't read [_The Harness Is the Product_](2026-05-21-the-harness-is-the-product.md), start there. It explains *why* A2E exists. This post explains *how to use it*.

---

## Part 1: The A2E Design Framework

Before we write any code, it's worth understanding how A2E is structured. The protocol isn't just a wire format — it's a **design framework** for building agent-environment systems. You can think of it as having three layers.

### Layer 1: The Wire Protocol

Every interaction between an agent and its environment is a typed NDJSON message. There are no SDK imports required on the wire — just UTF-8 lines with a JSON payload. The message type tells the runtime how to route it, and both sides agree on the schema via capability negotiation at session start.

```
tool/call/req      → Call a named function
env/reset/req      → Start a new episode
env/step/req       → Send an action, receive next_state + reward
memory/store/req   → Save a value
learn/feedback/req → Signal how well something went
learn/adapt/req    → Update routing weights from accumulated feedback
```

This is the same design philosophy as POSIX. The wire format is the interface. The implementations are swappable.

### Layer 2: The Plugin Runtime

The A2E host is a thin execution kernel. It loads plugins, routes messages to them, and manages session lifecycle. No capability-specific logic lives in the host itself.

```
A2EServer
  ├── Executor (message dispatch)
  │   ├── EnvPlugin     → env/reset, env/step, env/observe, env/close
  │   ├── ToolPlugin    → tool/list, tool/call
  │   ├── MemoryPlugin  → memory/store, memory/recall
  │   ├── LearnPlugin   → learn/feedback, learn/experience, learn/adapt
  │   └── (6 more capability namespaces)
  └── Transport (Direct / Subprocess / HTTP+SSE)
```

Each plugin registers for the message types it handles. The executor maintains a `type_to_plugins` dict that routes incoming messages by type. There is no global tool registry, no hardcoded capability list — everything is driven by what plugins are loaded.

### Layer 3: The Capability Namespaces

A2E defines 10 standard namespaces:

| Namespace | What it does |
|-----------|-------------|
| **env**  | RL environments: reset, step, observe, reward, close |
| **tools** | Named callable functions with structured I/O |
| **memory** | Three-tier storage: working, episodic, semantic |
| **proc** | Manage long-running subprocesses |
| **learn** | Feedback, experience replay, adaptation |
| **skills** | Named, versioned, sandboxed execution units |
| **toolkits** | Bundles of tools with shared configuration |
| **chains** | DAG pipelines with branching and fan-out |
| **mcp** | Bridge to Model Context Protocol servers |
| **subagents** | Multi-agent orchestration: spawn, delegate, merge |

This post focuses on the **env** namespace — the core of RL-style agent-environment interaction — and how it integrates with **tools**, **memory**, and **learn** to form a complete training loop.

---

## Part 2: Strategic Value — Why the Framework Matters

The A2E design framework has a claim worth unpacking: **it changes the economics of agent infrastructure**.

Here's the argument in three points.

### 1. Decoupling agent from environment

Without a protocol layer, your agent code is coupled to every backend it talks to. The tool definitions are in LangChain format. The memory calls go to Pinecone's SDK. The environment runner is Gymnasium. The feedback pipeline is a custom Lambda. Each backend has its own API, its own schema, its own failure modes. When you swap one, you rewrite the agent.

A2E decouples agent from environment behind a single typed message bus. The agent writes `memory/store/req`. The host routes it to whatever `MemoryPlugin` is loaded. Change the plugin — from in-memory dict to SQLite to Pinecone — and the agent never notices. The cost of churn drops from "rewrite the agent" to "swap the plugin."

### 2. Making the loop programmable

The most powerful thing A2E enables isn't tool calling or memory storage — it's the **programmable interaction loop** itself. The agent isn't a monolithic script with a hardcoded `while True` block. It's a protocol participant that negotiates capabilities, sends structured messages, receives events, records feedback, and adapts — all within the same session, all through the same transport.

This becomes critical for recursive self-learning: the loop *is* the infrastructure. The agent can improve between turns because `learn/adapt/req` runs in the same message flow as `env/step/req`. There's no separate training pipeline, no offline batch job, no vendor support ticket.

### 3. Making the infrastructure yours

Every plugin is a Python class you control. The `EnvPlugin` base class defines the contract — `on_reset`, `on_step`, `on_close` — but the implementation is yours. The memory backend is yours. The adaptation strategy is yours. The audit log is yours.

When training data is just `learn/feedback/req` messages stored in your audit JSONL, you're not a tenant on someone else's platform. You own the data, the format, and the extraction pipeline.

---

## Part 3: Building a Realistic Agent

Let's build a ReAct-style agent that connects to an A2E host, interacts with an environment, records trajectory data, and learns from feedback. We'll start from the code in `cookbook/agents/react_agent.py`.

### The Client Setup

The agent connects to an A2E host over HTTP+SSE:

```python
from a2e import A2EClient
from a2e.caps.env.client import EnvAPI
from a2e.caps.memory.client import MemoryAPI
from a2e.caps.learn.client import LearnAPI
from a2e.caps.tools.client import ToolAPI
from a2e.caps.skills.client import SkillAPI
from a2e.caps.chains.client import ChainsAPI

from a2e.core.transports import (
    build_transport, TransportConfig, HTTPTransportConfig
)
from a2e.caps.base.protocol import A2ECapability


class EnvClient:
    def __init__(self, logger):
        transport_config = TransportConfig(**{
            "type": "http",
            "config": HTTPTransportConfig(**{
                "base_url": "http://localhost:8765",
                "stream": "/stream",
                "send": "/send"
            })
        })

        self.transport = build_transport(transport_config, logger)
        self.client = A2EClient(
            transport=self.transport,
            logger=logger,
            agent_id="react-agent",
            auth_token="",
            agent_caps=[
                A2ECapability.TOOLKITS,
                A2ECapability.ENV,
                A2ECapability.PROC,
            ],
        )

        # Capability API wrappers
        self.env = EnvAPI(self.client)
        self.memory = MemoryAPI(self.client)
        self.learn = LearnAPI(self.client)
        self.tools = ToolAPI(self.client)
        self.skills = SkillAPI(self.client)
        self.chains = ChainsAPI(self.client)

    async def start(self):
        await asyncio.to_thread(self.client.connect)
        await asyncio.to_thread(self.memory.init)

    async def stop(self):
        await asyncio.to_thread(self.client.disconnect)
```

### Why This Matters as a Pattern

The `EnvClient` is the agent's single point of contact with the A2E runtime. Every capability the agent needs — environment stepping, memory recall, feedback recording, tool calling — flows through the same `A2EClient` instance. This is not an accident. The transport layer is a single NDJSON connection. Every capability is a set of message types routed through that connection. The agent doesn't maintain separate connections to a tool server, a memory server, and an environment server. It has one protocol session with one host that happens to run multiple plugins.

This is the decoupling in action. Want to change the transport from HTTP to direct in-process communication? Swap the transport config. Want to change the memory backend from in-memory to SQLite? Swap the plugin on the host. The agent code never changes.

### The ReAct Loop

With the client connected, the agent enters the main interaction loop. Here's the flow from `cookbook/agents/react_agent.py`:

```python
class A2EReActAgent:
    def __init__(self, rt_client, llm=None):
        self.rt_client = rt_client
        self.llm = llm
        self.history = []

    async def run(self, goal: str, env_name: str = "counter_env",
                  max_steps: int = 20) -> EpisodeTrajectory:
        # 1. Reset environment
        reset_resp = await asyncio.to_thread(
            self.rt_client.env.reset, env_name=env_name
        )
        obs = reset_resp.obs
        episode_id = obs.episode_id
        done, truncated = obs.done, obs.truncated

        trajectory = EpisodeTrajectory(
            episode_id=episode_id, env_name=env_name,
            goal=goal, initial_obs=obs.model_dump()
        )

        step_idx = 0
        while not self.rt_client.env.is_done(done, truncated) \
              and step_idx < max_steps:

            # Build context from env + memory
            memories = await asyncio.to_thread(
                self.rt_client.memory.retrieve, query=goal, limit=5
            )

            context = {
                "goal": goal,
                "observation": {"env": obs.model_dump(),
                                "history": self.history[-10:]},
                "memories": [str(m.content) for m in memories],
                "available_tools": [
                    t.name for t in self.rt_client.tools.list()
                ],
            }

            # Reason → select action
            thought = await self.reason(context)
            action = thought["action"]

            # Execute action by type
            t0 = time.monotonic()
            success = True
            try:
                if action["type"] == "tool":
                    result = await asyncio.to_thread(
                        self.rt_client.tools.call,
                        action["name"], action["input"]
                    )
                    observation_result = result.output
                    success = result.success

                elif action["type"] == "skill":
                    result = await asyncio.to_thread(
                        self.rt_client.skills.call,
                        action["name"], action["input"]
                    )
                    observation_result = result.output
                    success = result.success

                elif action["type"] == "env":
                    step_resp = await asyncio.to_thread(
                        self.rt_client.env.step,
                        episode_id, action["input"]
                    )
                    obs = step_resp.obs
                    done = step_resp.done
                    truncated = step_resp.truncated
                    observation_result = obs.model_dump()

                elif action["type"] == "chain":
                    result = await asyncio.to_thread(
                        self.rt_client.chains.run,
                        nodes=action["input"]["nodes"],
                        entry_node=action["input"]["entry_node"],
                        initial_input=action["input"].get(
                            "initial_input", {}
                        ),
                    )
                    observation_result = result.output
                    success = result.success

            except Exception as e:
                success = False
                observation_result = str(e)

            latency_ms = (time.monotonic() - t0) * 1000

            # Compute reward
            reward = await self.compute_reward(
                goal=goal, thought=thought,
                observation=observation_result, success=success,
            )
```

The loop has four dispatch branches — **tool**, **skill**, **env**, **chain** — because the A2E agent has access to all four capabilities simultaneously. This is the reality of a realistic agent: it doesn't just step an environment. It calls tools to gather information, invokes skills to run sandboxed logic, builds chains for multi-step pipelines, and takes environment actions to affect state. All four are first-class protocol messages.

### Learning from Each Step

After each step, the agent records feedback and stores episodic memory. This is where the loop closes:

```python
            # Record feedback
            await asyncio.to_thread(
                self.rt_client.learn.feedback,
                polarity=(
                    FeedbackPolarity.POSITIVE
                    if reward > 0 else FeedbackPolarity.NEGATIVE
                ),
                score=float(reward),
                dimension=(
                    FeedbackDimension.CORRECTNESS
                    if success else FeedbackDimension.PLAN_QUALITY
                ),
                confidence=1.0,
                prompt=goal,
                response=str(observation_result),
                model="a2e-react-agent",
                environment={
                    "env_name": env_name,
                    "episode_id": episode_id,
                    "step_id": step_idx,
                },
                source=FeedbackSource.ENV,
            )

            # Store episodic memory
            await asyncio.to_thread(
                self.rt_client.memory.remember,
                key={"episode_id": episode_id, "step_idx": step_idx},
                value={
                    "goal": goal, "thought": thought,
                    "action": action, "reward": reward,
                    "success": success,
                },
                tier="episodic",
                tags=["trajectory", "react", "rlm"],
            )

            # Periodic adaptation
            if step_idx > 0 and step_idx % 5 == 0:
                await asyncio.to_thread(
                    self.rt_client.learn.adapt
                )
```

The `learn.feedback()` call sends a structured signal — polarity, score, dimension, source, environment context — to the host's `LearnPlugin`. The `learn.adapt()` call triggers the adaptation strategy (UCB1, epsilon-greedy, softmax) to update routing weights. The agent improves between turns, not between training runs.

This is on-policy RL over a standard protocol. The policy that generated the experience is the same policy that gets updated. The credit assignment is exact. The learning is immediate.

---

## Part 4: Building the Harness

The harness is the other side of the protocol — the host that runs the environment, manages episodes, and delivers rewards. Let's build it in three layers.

### Layer 1: The Environment Plugin

Every A2E environment starts as a subclass of `EnvPlugin`:

```python
from a2e.caps.env.plugin import EnvPlugin
from a2e.caps.env.protocol import EnvState, EnvObservation


class CounterEnv(EnvPlugin):
    name = "counter"

    def on_reset(self, seed=None, options=None) -> EnvState:
        self.state = EnvState(**{"count": 0, "step_num": 0})
        return self.state

    def on_step(self, episode_id: str,
                action: Dict[str, Any]) -> EnvObservation:
        if not hasattr(self, "state"):
            raise RuntimeError("Env not reset. Call env/reset first.")

        if action.get("type") == "inc":
            self.state.count += 1

        reward = 1.0 if self.state.count == 5 else 0.0
        done = self.state.count >= 5
        truncated = False

        return EnvObservation(**{
            "episode_id": episode_id,
            "step_num": self.state.step_num,
            "state": self.state,
            "reward": reward,
            "done": done,
            "truncated": truncated,
            "info": {},
        })
```

The `EnvPlugin` base class handles all protocol-level concerns — message dispatch, req_id injection, error wrapping, audit logging. Your subclass only implements `on_reset()` and `on_step()`. The protocol layer takes care of the rest.

### Layer 2: The Host Adapter

The host adapter bridges the protocol layer to the environment plugin instances. It manages the mapping from `episode_id` back to the correct `EnvPlugin` instance and provides an optional **auto-learning hook** that records experiences without the agent having to call `learn/experience` separately:

```python
from a2e.caps.env.plugin import EnvPlugin
from env_registry import EnvRegistry


class EnvHostAdapter:
    def __init__(self, registry: EnvRegistry, learning=None):
        self.registry = registry
        self.learning = learning
        self._episode_to_env: Dict[str, EnvPlugin] = {}

    def reset(self, env_name: str, seed=None, options=None):
        env = self.registry.get(env_name)
        episode_id, state = env.reset(seed, options)
        self._episode_to_env[episode_id] = env
        return {"episode_id": episode_id, "state": state}

    def step(self, episode_id: str, action: Dict[str, Any]):
        env = self._get_env(episode_id)
        prev_state = env.observe()
        next_state, reward, done, info = env.step(action)

        # Auto-learning hook: every env step records an experience tuple
        if self.learning:
            self.learning.record_experience(
                state=prev_state, action=action,
                reward=reward, next_state=next_state,
                done=done, episode_id=episode_id,
            )

        return {
            "next_state": next_state, "reward": reward,
            "done": done, "info": info,
        }

    def observe(self, episode_id: str):
        env = self._get_env(episode_id)
        return {"state": env.observe(episode_id)}

    def close(self, episode_id: str):
        env = self._get_env(episode_id)
        env.close()
        self._episode_to_env.pop(episode_id, None)
        return {"closed": True}

    def _get_env(self, episode_id: str) -> EnvPlugin:
        if episode_id not in self._episode_to_env:
            raise ValueError(f"Unknown episode_id: {episode_id}")
        return self._episode_to_env[episode_id]
```

The auto-learning hook is the key architectural innovation. Every `env/step` call automatically produces a `(state, action, reward, next_state, done)` experience tuple. The agent doesn't have to call an additional API. The harness absorbs the integration so the agent doesn't have to think about it.

### Layer 3: Wiring It Into the A2E Server

The host adapter lives inside the A2E server as an `EnvPlugin`. The server wires it through configuration:

```yaml
# config.yaml
host_id: "a2e-training-host"
server:
  host: "0.0.0.0"
  port: 8765
transport:
  type: http
plugins:
  - name: counter_env
    type: env
    cls: cookbook.servers.counter_env.CounterEnv
    metadata:
      enabled: true
  - name: mymemory
    type: memory
    cls: cookbook.servers.memory.inmemory.InMemoryPlugin
    metadata:
      enabled: true
  - name: mylearning
    type: learn
    cls: cookbook.servers.learn.learn.InMemoryLearnPlugin
    metadata:
      enabled: true
```

And then started:

```python
from a2e.server import A2EServer
from a2e.schema import A2EHostConfig
from a2e.core.transports import build_transport

config = A2EHostConfig.from_yaml("config.yaml")
transport = build_transport(config.transport, logger)
server = A2EServer(config=config, transport=transport, logger=logger)
server.start()
```

The server loads the three plugins — `CounterEnv`, `InMemoryPlugin`, `InMemoryLearnPlugin` — into its executor. Each one registers for its message types. The agent connects and negotiates which capabilities it supports. The handshake completes, and the loop begins.

---

## Part 5: The Full Integration

With both sides built, here's what the complete data flow looks like:

```
AGENT                              HOST
  │                                 │
  ├── connect()                     │
  │    └── handshake (caps, auth) ──┤
  │                                 │
  ├── env.reset("counter_env") ────→│  EnvPlugin.on_reset()
  │    ←── obs {count: 0, done:F} ──┤  (episode_id assigned)
  │                                 │
  ├── memory.retrieve(goal) ──────→│  MemoryPlugin.retrieve()
  │    ←── [...memories] ───────────┤
  │                                 │
  ├── tools.list() ────────────────→│  ToolPlugin._list_tools()
  │    ←── [ToolDefinition...] ─────┤
  │                                 │
  ├── reason & plan action ──────── │  (LLM or heuristic planner)
  │                                 │
  ├── env.step({type:"inc"}) ─────→│  EnvPlugin.on_step()
  │    │                           │    auto-learning hook
  │    │                           │    → ExperienceBuffer.record()
  │    ←── obs {count:1, r:0} ─────┤
  │                                 │
  ├── learn.feedback(score=0) ────→│  LearnPlugin.record_feedback()
  │                                 │
  ├── memory.remember(step_data) ─→│  MemoryPlugin.store(episodic)
  │                                 │
  ├── (repeat until done)          │
  │                                 │
  ├── learn.adapt(strategy="ucb1")→│  LearnPlugin.adapt()
  │    ←── SkillPerformanceRecord───┤  (updated routing weights)
  │                                 │
  ├── env.close(episode_id) ───────→│  EnvPlugin.close()
```

### What Makes This Architecture Different

1. **Protocol-first, not SDK-first.** The agent and host communicate over typed NDJSON messages. They don't share imports, class hierarchies, or runtime state. The protocol is the contract.

2. **Multi-capability dispatch.** The agent can call tools, invoke skills, step the environment, run chains, and record learning — all through the same session. The executors routes by message type. Adding a new capability means adding a new plugin, not restructuring the agent.

3. **Learning is a first-class capability.** Feedback, experience, and adaptation are protocol messages, not bolt-on callbacks. The same message bus that carries `env/step/req` carries `learn/feedback/req`. The same executor that routes tool calls routes learning signals. The loop isn't a hack — it's architecture.

4. **The harness owns the integration.** Auto-learning hooks, episode-to-env tracking, reward computation — these live in the harness, not the agent. The agent sends simple messages (`env/step/req`, `learn/feedback/req`) and the harness does the orchestration. The agent stays simple. The harness stays composable.

---

## Conclusion: The Protocol Is the Interface

A2E is not a framework. It's not an SDK you import and build on top of. It's a **protocol** — a standard wire format that sits between your agent and everything it interacts with. The SDK is just a convenient way to speak that protocol from Python.

This distinction matters for the same reason POSIX mattered. You don't import "Linux" into your C program. You use `open()`, `read()`, `write()` — system calls that any Unix kernel implements. The program doesn't know or care which kernel it's running on. It knows the interface.

A2E is the same for agents. Your agent sends `env/reset/req`, `env/step/req`, `learn/feedback/req` over an NDJSON connection. The host on the other end could be a local process, a remote server, or a distributed cluster of microservices. The agent doesn't know or care. It knows the interface.

The cookbook code in `cookbook/agents/react_agent.py` and `cookbook/agents/deep_agent.py`, paired with the harness code in `cookbook/servers/counter_env.py` and `cookbook/servers/env_host_adapter.py`, demonstrates the pattern end-to-end. The agent's ReAct loop is stateless — every step is a fresh round-trip through the protocol. The harness manages state, episodes, and learning. The protocol is the glue.

Build your agents against the protocol. Own your harness. Swap your plugins. The agent never notices.


