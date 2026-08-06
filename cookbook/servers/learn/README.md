# Learn Plugin

Server-side implementation of the A2E learning capability with prime-agent-style refinement.

## Overview

The `Learn` plugin implements the full learning lifecycle:

1. **Feedback ingestion** — accepts scored rated turns from agents
2. **Experience recording** — stores on-policy and off-policy experience tuples
3. **Adaptation** — automatic plan → review → apply → stats workflow
4. **Refinement** — fine-grained control with plan, review, apply, rollback, history

## Files

| File | Purpose |
|---|---|
| `learn.py` | Main plugin class with message handlers |
| `store.py` | Persistence layer (JSONL + JSON) |
| `__init__.py` | Package init |

## Message Handlers

### Feedback

`learn/feedback/req` → `LearnFeedbackRequest`

Accepts feedback with scored rated turns. Updates per-component performance stats and stores the feedback for later refinement planning.

### Experience

`learn/experience/req` → `LearnExperienceRequest`

Records an experience tuple (state, action, reward, next_state) for on-policy or off-policy learning. Supports both component-scoped and global experiences.

### Adaptation

`learn/adapt/req` → `LearnAdaptRequest`

Triggers the full adaptation workflow:
1. Plan — generate refinement proposals from feedback and experiences
2. Review — auto-gate proposals (confidence, conflicts, history)
3. Apply — apply approved proposals atomically with before-snapshots
4. Rollback — available if apply fails
5. Stats — return updated ComponentPerformanceRecord list

### Refinement (per-step control)

| Message Type | Description |
|---|---|
| `learn/refinement/plan/req` | Generate proposals from feedback |
| `learn/refinement/review/req` | Gate a proposal (approve/reject) |
| `learn/refinement/apply/req` | Apply a proposal atomically |
| `learn/refinement/rollback/req` | Undo a previous apply |
| `learn/refinement/history/req` | Load full refinement log |

## Persistence

### JSONL Files (append-only)

- `experiences.jsonl` — experience tuples
- `feedbacks.jsonl` — feedback messages
- `refinements.jsonl` — refinement history (plan, review, apply, rollback events)

### JSON File (current state)

- `harness_state.json` — router weights, component configs, version checkpoint

### Storage Directory

Default: `~/.a2e/learn/`

Configurable via `LearnPlugin.config` with `storage_dir` key.

## Adaptation Strategies

See `AdaptStrategy` enum in `a2e/caps/learn/protocol.py`:

- `PPO` — Proximal Policy Optimization (default)
- `UCB1` — Upper Confidence Bound
- `EPSILON_GREEDY` — Random exploration
- `SOFTMAX` — Boltzmann exploration
- `CUSTOM` — User-defined

## Component Names

All learn operations accept a `component_name` parameter:

- `""` (empty) — all components
- `"my-tool"` — specific tool
- `"code_review"` — specific skill
- `"subagent-1"` — specific subagent

## Integration with react_agent

The `ReactAgent` in `cookbook/agents/react_agent.py` demonstrates integration:

```python
from cookbook.agents.react_agent import ReactAgent
from a2e.caps.learn.client import LearnAPI

agent = ReactAgent(
    llm_client=llm,
    tools=[...],
    skills=[...],
    learn=LearnAPI(host="localhost", port=8080),
)
```

The agent uses the refinement workflow (plan → review → apply) with rollback safety every N steps.