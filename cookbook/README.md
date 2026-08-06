# Cookbook Examples

This directory contains example implementations of A2E protocol plugins and agents.

## Structure

```
cookbook/
├── agents/          # Agent implementations (direct, react, http, subprocess)
├── servers/         # Server implementations (learn, skills, tools, memory, etc.)
│   ├── learn/       # Learning plugin with refinement capabilities
│   │   ├── learn.py # LearnPlugin implementation
│   │   ├── store.py # Persistence layer (JSONL + JSON state)
│   │   └── __init__.py
│   ├── skills/      # Skill plugins
│   ├── tools/       # Tool plugins
│   └── toolkits/    # Toolkit plugins
└── README.md        # This file
```

## Learn Plugin

The learn plugin implements the A2E learning capability with prime-agent-style refinement.

### Features

- **Feedback ingestion** — accepts `learn/feedback/req` messages with scored rated turns
- **Experience recording** — accepts `learn/experience/req` messages for on-policy and off-policy data
- **Adaptation** — `learn/adapt/req` triggers automatic plan→review→apply→stats workflow
- **Refinement** — fine-grained control via plan, review, apply, rollback, history operations
- **Persistence** — experiences, feedbacks, and refinements stored in JSONL; harness state in JSON

### API

#### Client-side (agent calls)

```python
from a2e.caps.learn.client import LearnAPI

# Fire-and-forget adaptation (server handles full workflow)
records = learn.adapt(component_name="my-tool", strategy=AdaptStrategy.PPO)

# Per-step refinement control
plan = learn.refine(component_name="my-tool", action="plan", strategy=AdaptStrategy.PPO)
review = learn.refine(component_name="my-tool", action="review", proposal=plan["proposals"][0])
result = learn.refine(component_name="my-tool", action="apply", proposal=plan["proposals"][0])
learn.refine(component_name="my-tool", action="rollback", refinement_id="ref-123")
history = learn.refine(component_name="my-tool", action="history")

# Stats and rewards
stats = learn.stats(component_name="my-tool")
learn.reward(component_name="my-tool", value=0.85)
```

#### Server-side (plugin implementation)

The `Learn` class in `servers/learn/learn.py` implements `LearnPlugin` and handles all message types:

| Message Type | Direction | Description |
|---|---|---|
| `learn/feedback/req` | Agent → Host | Submit feedback with scored turns |
| `learn/feedback/resp` | Host → Agent | Confirmation with updated stats |
| `learn/experience/req` | Agent → Host | Record an experience tuple |
| `learn/experience/resp` | Host → Agent | Confirmation with stored experience |
| `learn/adapt/req` | Agent → Host | Trigger full adaptation workflow |
| `learn/adapt/resp` | Host → Agent | Updated ComponentPerformanceRecord list |
| `learn/stats/req` | Agent → Host | Query performance stats |
| `learn/stats/resp` | Host → Agent | Stats response |
| `learn/reward/req` | Agent → Host | Send scalar reward signal |
| `learn/reward/resp` | Host → Agent | Confirmation |
| `learn/refinement/plan/req` | Agent → Host | Generate refinement proposals |
| `learn/refinement/plan/resp` | Host → Agent | Plan with proposals |
| `learn/refinement/apply/req` | Agent → Host | Apply a proposal atomically |
| `learn/refinement/apply/resp` | Host → Agent | Apply result with rollback info |
| `learn/refinement/rollback/req` | Agent → Host | Undo a previous apply |
| `learn/refinement/rollback/resp` | Host → Agent | Rollback confirmation |
| `learn/refinement/review/req` | Agent → Host | Review a proposal (confidence gate) |
| `learn/refinement/review/resp` | Host → Agent | Review result (approved/rejected) |
| `learn/refinement/history/req` | Agent → Host | Load refinement history |
| `learn/refinement/history/resp` | Host → Agent | Full refinement log |

### Adaptation Strategies

The `AdaptStrategy` enum defines available strategies:

| Strategy | Value | Description |
|---|---|---|
| `PPO` | `"ppo"` | Proximal Policy Optimization — policy gradient with clipping |
| `UCB1` | `"ucb1"` | Upper Confidence Bound — explore/exploit based on confidence intervals |
| `EPSILON_GREEDY` | `"epsilon_greedy"` | Random exploration with epsilon probability |
| `SOFTMAX` | `"softmax"` | Boltzmann exploration over value estimates |
| `CUSTOM` | `"custom"` | User-defined strategy |

### Component Names

The `component_name` parameter is used across all learn operations to target specific components:

- `component_name=""` (empty) — affects all components
- `component_name="my-tool"` — targets a specific tool
- `component_name="code_review"` — targets a specific skill
- `component_name="subagent-1"` — targets a specific subagent

### Persistence

The learn plugin stores data in two formats:

1. **JSONL files** — append-only log of experiences, feedbacks, and refinements
2. **JSON file** — current harness state (router weights, component configs)

Default storage directory: `~/.a2e/learn/`

### Example Usage with react_agent

The `react_agent.py` demonstrates how to integrate the learn plugin into an agent loop:

```python
from cookbook.agents.react_agent import ReactAgent
from a2e.caps.learn.client import LearnAPI
from a2e.caps.learn.protocol import AdaptStrategy

agent = ReactAgent(
    llm_client=llm,
    tools=[...],
    skills=[...],
    learn=LearnAPI(host="localhost", port=8080),
)

# The agent automatically calls refinement every N steps
# (default: every 5 steps, with component_name="react-agent")
result = agent.run("your task here")
```

The agent uses the refinement workflow (plan → review → apply) instead of the simple `adapt()` call, giving it per-proposal control and rollback safety.

### Server Setup

```python
from cookbook.servers.learn.learn import Learn
from a2e.core.host import A2EHost

host = A2EHost()
host.register_plugin(Learn())
host.start()
```

The Learn plugin auto-discovers and registers all 18 message types. No manual configuration needed.