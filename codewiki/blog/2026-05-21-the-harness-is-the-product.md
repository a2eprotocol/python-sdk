---
title: "The Harness Is the Product"
date: 2026-05-21
authors: ["A2E Protocol Team"]
tags: ["launch", "protocol", "agents", "vendor-lock", "recursive-learning", "adaptive-training"]
summary: "Why the AI industry is sleepwalking into harness vendor lock-in, and how the A2E protocol gives enterprises back ownership of their agent infrastructure."
---

# The Harness Is the Product

## And you don't own yours.

---

Every AI agent platform today sells you the same story: "Just use our SDK, our runtime, our memory store, our tool definitions, our model routing — and your agents will be *magical*."

They're not wrong about the magic. They're wrong about who owns the wand.

Here's the uncomfortable truth: **the harness is the product**. The model is a commodity. The prompts are ephemeral. What persists — what compounds in value — is the infrastructure that wraps the model: the tool definitions, the memory schemas, the feedback loops, the process orchestration, the skill routing. That's the harness. And if it lives inside someone else's platform, *you don't own your agents.*

A2E exists to change that.

---

## The Lock-In Nobody Talks About

Everyone talks about model lock-in. Nobody talks about **harness lock-in**.

Model lock-in is a solved problem. Swap GPT-4 for Claude. Swap Claude for Gemini. The API surface is nearly identical — a chat completion endpoint, some tool-calling conventions, a streaming response format. It takes an afternoon to switch models.

Harness lock-in is the insidious kind. It's the kind that takes *years* to unwind.

Consider what happens when you build on a proprietary agent platform:

- Your **tool definitions** are encoded in their schema format. Not OAS. Not JSON Schema. *Their* format.
- Your **memory architecture** is their vector store with their embedding model and their retrieval API. Your agents can't think without it.
- Your **feedback loops** are their evaluation pipeline. Your RLHF data? Locked in their format.
- Your **process orchestration** — subprocesses, file I/O, shell commands — routes through their sandbox. You can't move it without rewriting every agent.
- Your **multi-agent coordination** uses their proprietary message bus. No interoperability. No escape hatch.

After 18 months, you don't have agents. You have *their* agents. Running on *their* runtime. Storing state in *their* databases. Generating training data in *their* format.

You're not a customer. You're a tenant.

---

## POSIX for AI Agents

In 1969, Ken Thompson and Dennis Ritchie didn't build Unix by writing applications. They built a **standard interface** between programs and the operating system — file descriptors, pipes, signals, process control. That interface — later formalized as POSIX — meant that any program could run on any Unix system. The interface *was* the product. The implementations were interchangeable.

A2E is POSIX for AI agents.

It defines a **standard wire protocol** — NDJSON-based, typed, versioned — that sits between an agent and its environment. The agent doesn't know or care who built the memory store, the tool runtime, or the process manager. It sends `memory/store/req`, it gets `memory/store/resp`. It sends `tool/call/req`, it gets `tool/call/resp`. It sends `learn/feedback/req`, the environment learns.

```
┌──────────────────────────────────────────────────────┐
│                    YOUR AGENT                         │
│          Any model. Any framework. Any vendor.        │
├──────────────────────────────────────────────────────┤
│                  A2E PROTOCOL                         │
│       10 capability namespaces, 80+ message types     │
│       NDJSON wire format, Pydantic-validated          │
├──────────────────────────────────────────────────────┤
│              YOUR ENVIRONMENT                         │
│    Swap the memory plugin. Swap the tool backend.     │
│    Swap the model. Swap the entire runtime.           │
│    The agent never notices.                           │
└──────────────────────────────────────────────────────┘
```

The protocol is the interface. The plugins are the implementations. **You own the protocol. You swap the plugins.**

---

## The 10 Capabilities That Break Lock-In

A2E defines ten capability namespaces — each one a vector where vendor lock-in typically takes root, and each one where A2E hands you the key:

| Capability | What It Does | Lock-In It Breaks |
|-----------|-------------|-------------------|
| **tools** | Call named functions with structured I/O | Proprietary tool schemas, vendor-specific function calling |
| **memory** | 3-tier storage: working, episodic, semantic | Vendor vector stores, proprietary embedding APIs |
| **env** | RL environments: reset, step, observe, reward | Vendor-specific gym wrappers, closed simulation APIs |
| **proc** | Manage long-running subprocesses | Sandboxed shell access tied to vendor runtime |
| **learn** | Feedback, experience replay, adaptation | Proprietary RLHF pipelines, vendor-owned eval data |
| **skills** | Named, versioned, sandboxed execution units | Vendor-specific skill registries and marketplaces |
| **toolkits** | Bundles of tools with shared configuration | Vendor tool bundles that can't be moved |
| **chains** | DAG pipelines with branching and fan-out | Proprietary workflow engines, closed orchestration |
| **mcp** | Bridge to Model Context Protocol servers | MCP server lock-in to specific host implementations |
| **subagents** | Multi-agent orchestration: spawn, delegate, merge | Vendor-specific multi-agent frameworks with no interoperability |

Each capability is a **plugin**. Each plugin implements a **standard protocol**. Want to swap your SQLite memory backend for Pinecone? Write a new `MemoryPlugin`. Want to swap your tool executor from a sandboxed Docker runtime to local execution? Swap the `ToolPlugin`. The agent code doesn't change. The protocol doesn't change. Only the implementation changes.

That's not abstraction. That's **ownership**.

---

## Recursive Self-Learning: The Loop That Changes Everything

Here's the paradigm shift that most agent platforms aren't ready for: **agents that learn from their own environment interaction — not just from human annotations, but from the feedback loops inherent in tool execution, process outcomes, and multi-agent coordination.**

This is Recursive Self-Learning. And it's not science fiction. It's three A2E capabilities working in concert:

```
         ┌──────────────────────────────────────┐
         │                                      │
         ▼                                      │
   ┌──────────┐    env/step     ┌──────────┐   │
   │   ENV    │───────────────▶ │  AGENT   │   │
   │ Plugin   │    reward       │          │   │
   └──────────┘                 └────┬─────┘   │
         ▲                           │         │
         │              learn/feedback/req      │
         │                           │         │
         │              ┌────────────▼─────┐   │
         │              │   LEARN Plugin   │   │
         │              │                  │   │
         │              │  • Record reward │   │
         │              │  • Store (s,a,r, │   │
         │              │    s',done)      │   │
         │              │  • Adapt routing │   │
         │              │  • UCB1 / eps-   │   │
         │              │    greedy /      │   │
         │              │    softmax       │   │
         │              └────────────┬─────┘   │
         │                           │         │
         │              learn/adapt/req        │
         │                           │         │
         │              ┌────────────▼─────┐   │
         │              │  SKILL Plugin    │   │
         │              │                  │   │
         │              │ Updated routing  │───┘
         │              │ weights, better  │
         │              │ skill selection  │
         │              └──────────────────┘
         │                           
         └── Updated environment state
             from better actions
```

### The Loop in Practice

1. **Agent acts** — Calls a tool, takes an env step, delegates to a subagent
2. **Environment responds** — Returns reward, observation, success/failure
3. **Feedback is recorded** — `learn/feedback/req` with polarity, score, dimension, source (human, env, or self)
4. **Experience is stored** — `learn/experience/req` with full (state, action, reward, next_state, done) tuples
5. **Adaptation triggers** — `learn/adapt/req` updates skill routing weights using UCB1, epsilon-greedy, or softmax strategies
6. **Agent improves** — Better skill selection, better tool choices, better action policies — *on your infrastructure, with your data*

The feedback model supports four dimensions of evaluation: **correctness**, **helpfulness**, **safety**, and **plan quality**. It supports three sources: **human** annotation, **environment** signals (test pass/fail, tool errors, reward from env/step), and **self** critique.

And here's the critical part: `CORRECTIVE` feedback — "you should have done X instead" — automatically generates **on-policy advantage estimates** via `to_preference_pair()`. Every correction your human annotators make becomes a policy improvement signal. Every environment reward becomes an on-policy reward sample via `to_reward_sample()`. The data compounds. The agent improves. And the data lives in **your** environment, not a vendor's cloud.

### Why This Breaks Without Open Protocols

On a proprietary platform, the feedback loop is closed. The platform owns the feedback format. The platform owns the experience store. The platform decides whether you get access to your own training data. The platform decides whether adaptation happens, and how.

With A2E, the loop is **open by design**:
- Feedback schema is standardized → any evaluation pipeline can produce it
- Experience tuples are standardized → any RL framework can consume them
- Adaptation strategies are pluggable → swap UCB1 for your custom strategy
- The entire data pipeline is auditable → every `learn/feedback/req` is logged in the audit trail

**Your agents. Your data. Your learning loop. Your choice of how to improve them.**

---

## Adaptive Training: Test-Time Compute Meets Train-Time Feedback

The AI research community is converging on a radical idea: **the distinction between training and deployment is collapsing.**

In 2024, the conversation was about "test-time compute" — giving models more tokens to think at inference time, watching accuracy climb as you let them reason longer. Chain-of-thought, tree-of-thought, best-of-N sampling. The insight: *inference is trainable*. More compute at test time yields better answers.

In 2025, the conversation shifted to "test-time training" — actually updating model weights during deployment. Not just prompting differently, but *learning* differently. Fine-tuning on the fly. Adapting to the distribution shift you're seeing right now. The paper you're reading, the codebase you're navigating, the user you're helping — they're all different from the training set. The model should adapt.

Here's what nobody has built yet: **the infrastructure that makes test-time training and train-time testing operational.**

That's what A2E's learn capability is.

### Test-Time Training Through A2E

Test-time training means: while the agent is deployed and serving users, it's also *learning*. Not in the background, not in a separate pipeline — *in the same protocol session, through the same message bus, against the same audit trail.*

With A2E, test-time training isn't a research experiment. It's a protocol message:

```
┌─────────────────────────────────────────────────────────────────┐
│                     TEST-TIME TRAINING FLOW                      │
│                                                                  │
│  1. Agent acts in production                                     │
│     tool/call/req  →  tool/call/resp                             │
│                                                                  │
│  2. Outcome produces feedback automatically                      │
│     ┌─────────────┐    ┌──────────────┐    ┌───────────────┐    │
│     │ Tool error?  │───▶│ env reward?  │───▶│ Human thumbs  │    │
│     │ → NEGATIVE   │    │ → score      │    │ down? → score │    │
│     └─────────────┘    └──────────────┘    └───────────────┘    │
│              │                │                      │            │
│              └────────────────┼──────────────────────┘            │
│                               ▼                                  │
│     learn/feedback/req  {polarity, score, dimension, source}     │
│                               │                                  │
│  3. Experience stored for replay                                 │
│     learn/experience/req  {state, action, reward, next_state}   │
│                               │                                  │
│  4. Adaptation triggers — weights update in real-time            │
│     learn/adapt/req  {skill_name, strategy: "ucb1"}             │
│                               │                                  │
│  5. Next agent turn uses updated routing                         │
│     Better skill selection. Better tool choice.                  │
│     The agent got smarter *during deployment*.                   │
└─────────────────────────────────────────────────────────────────┘
```

The key insight: A2E doesn't just *record* the feedback. It makes the feedback **operationally actionable** within the same session. The `learn/adapt/req` message triggers immediate adaptation — updated `SkillPerformanceRecord` values, changed routing weights, different skill selection on the next turn. The agent improves *between turns*, not between training runs.

And because every message flows through the audit log, you have a complete, timestamped, queryable record of:

- What the agent did (`tool/call/req`)
- What happened (`tool/call/resp`, `env/step/resp`)
- What feedback was given (`learn/feedback/req`)
- What adaptation occurred (`learn/adapt/req`)
- What the new performance baseline is (`learn/stats/req`)

This isn't just test-time training. It's **auditable test-time training**. You can prove the agent improved. You can prove *why*. You can roll it back if it didn't.

### Train-Time Testing: The Reverse Loop

But here's the part that flips the paradigm: the same infrastructure that enables test-time training also enables **train-time testing**.

In traditional ML, you train on one dataset and test on another. In the agent world, your "training" is the agent's live interaction with environments, and your "testing" is whether those interactions actually produce good outcomes. The question isn't "did the model pass the benchmark?" — it's "is the agent *actually effective* in the environment it's deployed in?"

A2E's cross-capability integration makes this operational:

**env/step rewards flow into learn/feedback automatically.** When an agent takes an action in an RL environment and receives a reward, that reward isn't just a number in a tensor. It's a structured `Feedback` signal with `source=ENV`, a `score` normalized to [-1.0, +1.0], a `dimension` (correctness, helpfulness, safety), and a `correlation_id` linking it back to the specific action. The environment *is* the test. The test *is* the training data.

```python
from a2e.caps.env.client import EnvAPI
from a2e.caps.learn.client import LearnAPI

env = EnvAPI(client)
learn = LearnAPI(client)

# Reset the environment — start the "test"
resp = env.reset(env_name="code_review_env")
episode_id = resp.episode_id

while True:
    # Agent takes action (this is both testing AND generating training data)
    action = select_action(resp.observation)
    step_resp = env.step(episode_id, action)

    # The environment reward IS the test score AND the training signal
    if step_resp.observation.reward != 0:
        learn.feedback(
            polarity="POSITIVE" if step_resp.observation.reward > 0 else "NEGATIVE",
            score=step_resp.observation.reward,
            dimension="CORRECTNESS",
            source="ENV",  # <-- This is the key. The environment is the evaluator.
            correlation_id=step_resp.observation.step_id,
        )

    # Also store the full experience tuple for off-policy replay
    learn.experience([{
        "state": {"obs": step_resp.observation.state},
        "action": {"type": action.action_type, "payload": action.payload},
        "reward": step_resp.observation.reward,
        "next_state": {"obs": step_resp.observation.state},
        "done": step_resp.observation.done,
        "episode_id": episode_id,
    }])

    if step_resp.observation.done:
        break

# After the episode, adapt routing weights based on what worked
records = learn.adapt(skill_name="code_review", strategy="ucb1")
for r in records:
    print(f"{r.skill_name}: avg_score={r.avg_score:.2f}, "
          f"success_rate={r.calls_success/r.calls_total:.0%}")
```

In this loop, there is **no separate testing phase**. The environment step *is* the test. The reward signal *is* the evaluation. The experience tuple *is* the training sample. The adaptation *is* the parameter update. Train and test collapse into a single operational loop.

### The Feedback Spectrum: Three Sources, Five Dimensions

A2E's feedback model isn't binary. It's a structured signal that captures *why* something was good or bad:

**Three feedback sources:**

| Source | Origin | Example |
|--------|--------|---------|
| `HUMAN` | Human annotator | "That code review missed a security vulnerability" |
| `ENV` | Environment signal | Test suite failed (reward = -0.8), page loaded successfully (reward = +0.5) |
| `SELF` | Model self-critique | "I should have used a more specific search query" |

**Five feedback dimensions:**

| Dimension | What It Evaluates | Train-Time Testing Use Case |
|-----------|-------------------|----------------------------|
| `correctness` | Is the answer right? | Automated test pass/fail → reward model |
| `helpfulness` | Was it useful? | User satisfaction signal → on-policy reward |
| `safety` | Was it safe? | Red-team probe → safety reward head |
| `tone` | Was the tone appropriate? | Customer interaction → style preference |
| `plan_quality` | Was the strategy good? | Multi-step task → planning reward model |

Each dimension can be trained independently. A `correctness` reward model and a `safety` reward model are different heads on the same infrastructure. You don't need separate pipelines. You don't need separate data formats. You send `learn/feedback/req` with `dimension="safety"`, and the `LearnPlugin` routes it to the right training consumer.

### On-Policy RL: Learn From What You Just Did

The most powerful learning signal in A2E is **on-policy** — the agent learns from actions it just took, in the session it's currently running. This is how real RL works: the policy generates experience, the experience updates the policy, the updated policy generates better experience. The loop is tight, the credit assignment is exact, and the learning is immediate.

A2E's `learn/feedback` + `learn/adapt` in the same session is on-policy RL by design:

```python
from a2e.caps.env.client import EnvAPI
from a2e.caps.learn.client import LearnAPI

env = EnvAPI(client)
learn = LearnAPI(client)

# On-policy loop: act → observe → feedback → adapt → act again
resp = env.reset(env_name="sql_generation")
episode_id = resp.episode_id

for step in range(max_steps):
    # Current policy selects action
    action = policy.select(resp.observation)
    step_resp = env.step(episode_id, action)

    # On-policy feedback: reward from the env for the action THIS policy just took
    learn.feedback(
        polarity="POSITIVE" if step_resp.observation.reward > 0 else "NEGATIVE",
        score=step_resp.observation.reward,
        dimension="CORRECTNESS",
        source="ENV",
        correlation_id=step_resp.observation.step_id,
    )

    # Immediate adaptation: policy updates before the next step
    # This IS on-policy RL — the policy that generated the experience
    # is the same policy that gets updated
    learn.adapt(skill_name="sql_generation", strategy="ucb1")

    if step_resp.observation.done:
        break
```

The `Feedback.to_reward_sample()` method converts each on-policy step into a reward model training sample — the prompt, the response the *current policy* produced, the reward it received, and the confidence weighting:

```python
{
    "prompt": "Generate SQL to find users with >10 orders",
    "response": "SELECT user_id FROM orders GROUP BY user_id HAVING COUNT(*) > 10",
    "score": 0.85,
    "dimension": "correctness",
    "weight": 0.95,
    "source": "env",
}
```

Because the feedback is tied to the action the current policy just took, you avoid the distribution mismatch that plagues off-policy methods. The advantage estimates are correct. The policy gradient is unbiased. The agent learns the right thing from the right experience.

CORRECTIVE feedback from humans works the same way — but it's even richer. When an annotator says "you should have used `read_file` instead of `exec`", that's an on-policy correction: the current policy produced `exec`, and the human provides the counterfactual action. `Feedback.to_preference_pair()` structures this as an on-policy advantage signal:

```python
learn.feedback(
    polarity="CORRECTIVE",
    score=-0.5,
    dimension="CORRECTNESS",
    source="HUMAN",
    prompt="Read the file at /etc/hostname",
    response="exec('cat /etc/hostname')",        # What the current policy did
    correction="read_file('/etc/hostname')",      # What it should have done
    confidence=0.95,
)
```

This yields a structured advantage signal:

```python
{
    "prompt": "Read the file at /etc/hostname",
    "chosen": "read_file('/etc/hostname')",       # Higher-value action
    "rejected": "exec('cat /etc/hostname')",      # Lower-value action (current policy)
    "dimension": "correctness",
    "confidence": 0.95,
}
```

On closed platforms, this on-policy loop doesn't exist. The feedback goes into their pipeline. The adaptation is a support ticket. The agent can't learn between turns because the platform doesn't expose `learn/adapt/req`. The policy that generated the experience is not the policy that gets updated — if it gets updated at all.

### Off-Policy RL: Learn From Everything You've Ever Done

On-policy learning is powerful but sample-inefficient — you can only learn from what the current policy just did. Off-policy RL solves this: learn from *any* experience, regardless of which policy generated it. Historical data, other agents' experience, even human demonstrations — they all go into the replay buffer.

A2E's `learn/experience` endpoint is the off-policy replay buffer:

```python
from a2e.caps.learn.client import LearnAPI
from a2e.caps.learn.protocol import Experience

learn = LearnAPI(client)

# Store experience tuples from any source — current policy, old policy,
# other agents, human demonstrations
learn.experience([
    Experience(
        state={"context": "code_review", "file": "auth.py", "lines": "40-55"},
        action={"skill": "security_audit", "tool": "grep", "pattern": "password"},
        reward=-0.8,   # Missed a hardcoded credential
        next_state={"context": "code_review", "findings": ["hardcoded_pwd"]},
        done=False,
        episode_id="ep_42",
        step=3,
    ),
    Experience(
        state={"context": "code_review", "findings": ["hardcoded_pwd"]},
        action={"skill": "patch_writer", "tool": "write_file", "path": "auth.py"},
        reward=0.9,    # Correct patch generated
        next_state={"context": "code_review", "patched": True},
        done=True,
        episode_id="ep_42",
        step=4,
    ),
])
```

These experience tuples are stored by the `LearnPlugin` and can be replayed later by any off-policy algorithm — Q-learning, SAC, TD3, or your custom method. The key properties that make this work:

**1. Source-agnostic replay.** The `Experience` model doesn't encode *which policy* generated it. It captures `state`, `action`, `reward`, `next_state`, `done` — the RL primitives. Your off-policy algorithm handles the importance sampling correction. The protocol just delivers the data.

**2. Episode correlation.** The `episode_id` and `step` fields let you reconstruct full trajectories from the replay buffer — essential for multi-step RL, Hindsight Experience Replay (HER), and trajectory-level reward models.

**3. Cross-session accumulation.** Unlike on-policy learning (which discards old experience), `learn/experience` tuples persist across sessions. Yesterday's deployment generates today's replay data. Last week's agent generates this week's off-policy training batch. The data compounds.

**4. Cross-agent sharing.** Subagent experiences can be stored in a shared replay buffer. The researcher's failure becomes the coder's training data. The reviewer's corrections become the writer's policy improvements. Multi-agent off-policy RL — without a proprietary message bus.

```python
# After a multi-agent episode, merge all subagent experiences
for sid in [researcher.subagent_id, coder.subagent_id, reviewer.subagent_id]:
    sub_experiences = await subagents.collect_experiences(sid)
    learn.experience(sub_experiences)  # All go into the shared replay buffer

# Later: off-policy training on the accumulated replay
# (Your LearnPlugin implements the sampling strategy)
stats = learn.stats()  # Check buffer size and skill performance
learn.adapt(strategy="custom")  # Your off-policy algorithm
```

### On-Policy vs. Off-Policy: When to Use Which

| Aspect | On-Policy (feedback + adapt) | Off-Policy (experience + replay) |
|--------|------------------------------|----------------------------------|
| Data source | Current session, current policy | Any session, any policy, any agent |
| Sample efficiency | Low — can't reuse old data | High — replay buffer recycles everything |
| Credit assignment | Exact — the policy that acted is the policy that learns | Approximate — importance sampling corrects for distribution shift |
| Latency | Immediate — adapt between turns | Batched — train offline on accumulated replay |
| Best for | Fast adaptation in production, test-time training | Long-term skill improvement, cross-agent learning |
| A2E messages | `learn/feedback/req` → `learn/adapt/req` | `learn/experience/req` → `learn/adapt/req` (batch) |

The real power: **you run both simultaneously.** On-policy `learn/feedback` + `learn/adapt` keeps the agent sharp in the current session. Off-policy `learn/experience` accumulates the data for larger training runs. The same `LearnPlugin` handles both. The same audit trail logs both. The same `SkillPerformanceRecord` tracks the outcomes of both.

**Every production interaction becomes a training sample.** Every human correction becomes an on-policy advantage signal. Every environment reward becomes a reward model data point. Every experience tuple becomes off-policy replay data. The agent learns on-policy while it works and off-policy while it sleeps. The data compounds. The moat deepens. And it's all in your `LearnPlugin`, your backend, your format.

### Adaptation Strategies: From Bandits to Custom

The `learn/adapt` endpoint supports four strategies, each representing a different philosophy of how agents should improve:

| Strategy | Philosophy | When to Use |
|----------|------------|-------------|
| `ucb1` | Optimism in the face of uncertainty — explore skills you're unsure about | Early deployment, skill A/B testing |
| `epsilon_greedy` | Mostly exploit the best skill, occasionally try alternatives | Stable deployment with controlled exploration |
| `softmax` | Probability proportional to estimated value — smooth exploration | Continuous deployment, graceful degradation |
| `custom` | Your strategy. Your algorithm. Your `LearnPlugin`. | Enterprise-specific adaptation policies |

The `SkillPerformanceRecord` — rolling stats per skill: `calls_total`, `calls_success`, `calls_failed`, `avg_duration_ms`, `avg_score`, `p95_duration_ms` — gives you the data to make these decisions. You can query it anytime with `learn/stats/req`.

### Why This Only Works With Open Protocols

You cannot do test-time training on a closed platform. Here's why:

1. **You can't access the feedback loop.** On a proprietary platform, feedback goes into *their* evaluation pipeline. You can't pipe it to *your* reward model. You can't run on-policy adaptation from *their* corrections. You can't accumulate off-policy replay data from *their* experience. The data is theirs.

2. **You can't trigger adaptation.** On a closed platform, adaptation is either "fine-tune in our UI" or "submit a support ticket." You can't send `learn/adapt/req` programmatically. You can't trigger UCB1 exploration mid-session. You can't implement custom adaptation policies.

3. **You can't observe what changed.** On a closed platform, the model gets "better" — but you can't audit *why*. You can't see the `SkillPerformanceRecord` that shows the routing weight changed because skill X had a 0.82 avg_score over 50 calls. You can't verify. You can't debug. You can't govern.

4. **You can't run the reverse loop.** Train-time testing requires that environment signals flow back into learning. On a closed platform, the env and learn capabilities are separate products with separate APIs and separate data stores. They don't talk to each other. The reward from `env/step` doesn't automatically become a `learn/feedback` signal. You have to build that bridge yourself — if they even let you access both.

A2E makes all four of these possible by design, because the protocol is the interface, the plugins are yours, and the data flows through a standard wire format you can inspect, route, and audit at every step.

---

## The Multimodality Multiplier

The agent platforms of 2024-2025 were built for chat. Single-turn. Text in, text out. Maybe a function call. Maybe a document upload.

The agents of 2026 need **multimodal environments** — not just multimodal *models* (GPT-4o can see images, great), but multimodal *interaction*:

- **Code execution** — spawn a process, write to stdin, read from stdout, signal, kill
- **Browser automation** — click, type, screenshot, wait for DOM changes
- **File systems** — read, write, search, monitor
- **RL environments** — reset, step, observe, render in any modality (text, RGB, audio)
- **Multi-agent coordination** — spawn a researcher, a coder, and a reviewer; they message each other; they merge results
- **Chain pipelines** — define a DAG that fans out across tools, merges results, branches on conditions

A2E's ten capabilities aren't a random collection. They're the **minimum set of primitives** that an agent needs to interact with *any* environment in *any* modality:

- **tools** gives you structured function calling (API interactions, data queries)
- **proc** gives you arbitrary process execution (code, shells, long-running services)
- **env** gives you RL-style step loops (simulators, games, robotics, browser automation)
- **memory** gives you persistent state across turns and sessions
- **subagents** gives you multi-agent fan-out and coordination
- **chains** gives you DAG orchestration
- **mcp** gives you interoperability with the growing MCP ecosystem
- **learn** closes the loop with feedback and adaptation

No single platform offers all of these with an open protocol. They offer *their version* of some of these, locked to *their runtime*, encoded in *their format*.

A2E offers **all of them** through a **standard protocol** that any implementation can speak.

---

## Subagents: Orchestration Without a Platform Tax

Consider the multi-agent problem. You want to:

1. Spawn a **researcher** agent with isolated memory and restricted tools
2. Spawn a **coder** agent with shared memory and full tool access
3. Spawn a **reviewer** agent with a snapshot of memory at spawn time
4. Have them exchange intermediate results
5. Merge their outputs with a voting strategy

On a proprietary platform, this is either impossible or requires their proprietary orchestration layer — with their message bus, their agent registry, their proprietary event format.

With A2E's subagents capability:

```python
from a2e.caps.subagents.client import SubagentClient

subagents = SubagentClient(transport)

# Spawn three specialist agents
researcher = await subagents.spawn(
    name="researcher", model="claude-3.5-sonnet",
    role="research", capabilities=["tools", "memory"],
)
coder = await subagents.spawn(
    name="coder", model="gpt-4",
    role="engineering", capabilities=["tools", "memory"],
)
reviewer = await subagents.spawn(
    name="reviewer", model="claude-3.5-sonnet",
    role="review", capabilities=["tools", "memory"],
)

# Delegate tasks
await subagents.delegate(subagent_id=researcher.subagent_id, ...)
await subagents.delegate(subagent_id=coder.subagent_id, ...)
await subagents.delegate(subagent_id=reviewer.subagent_id, ...)

# Await all, then merge
results = await asyncio.gather(*[
    subagents.await_result(sid) for sid in [researcher, coder, reviewer]
])
merged = await merge([r.subagent_id for r in results], strategy="voting")
```

No platform tax. No proprietary message bus. No lock-in. The subagent protocol — `SUBAGENT_SPAWN_REQ`, `SUBAGENT_DELEGATE_REQ`, `SUBAGENT_AWAIT_REQ`, `SUBAGENT_MERGE_REQ` — is standardized. Any A2E-compatible host can run it.

And the isolation model gives you **fine-grained control** over each subagent's access:

| Scope | Memory | Tools | Use Case |
|-------|--------|-------|----------|
| `shared` | Parent's memory | Parent's tools | Trusted collaborator |
| `restricted` | Parent's memory | Filtered tools | Default — safe delegation |
| `isolated` | Own namespace | Own namespace | Sandbox, red team |
| `snapshot` | Copy at spawn | Filtered tools | Reviewer, auditor |

This isn't just multi-agent. This is **multi-agent with enterprise-grade isolation** — and the protocol belongs to you.

---

## The Enterprise Play: Own Your Harness

For enterprises building AI agents, the message is blunt:

**If your agent infrastructure lives on someone else's platform, you are building on rented land.**

The model will get cheaper. The model will get better. The model will get swapped. What won't change is the cost and risk of *rewriting your entire harness* when your platform vendor:

- Changes their API (again)
- Discontinues a feature you depend on
- Raises pricing on the only component you can't move
- Goes down, and you can't fail over because your agent state is trapped in their session store
- Gets acquired, and the new owner has different priorities

A2E gives enterprises a different contract:

### 1. Own Your Protocol
The A2E wire format is open. NDJSON. 80+ typed message types. Pydantic-validated. Versioned. You can implement it in any language. You can inspect every message. You can build monitoring, compliance, and governance on top of it — because you can see every `tool/call/req`, every `memory/store/req`, every `learn/feedback/req` in your audit logs.

### 2. Own Your Plugins
The host is a thin execution kernel. All capability logic lives in plugins. Plugins you write. Plugins you deploy. Plugins you can swap. Want a memory backend that hits your existing Pinecone instance? Write a `MemoryPlugin`. Want a tool executor that runs in your Kubernetes cluster with your RBAC? Write a `ToolPlugin`. Want a learning adapter that feeds your proprietary RLHF pipeline? Write a `LearnPlugin`.

### 3. Own Your Data
Every feedback signal, every experience tuple, every skill performance record — it flows through a protocol you control, into a plugin you operate, stored in a backend you manage. Your on-policy reward samples. Your off-policy replay buffer. Your competitive moat. Not a vendor's training dataset.

### 4. Own Your Models
A2E is model-agnostic by design. Subagents can run different models. Your researcher can use Claude. Your coder can use GPT-4. Your reviewer can use Gemini. You route to the model that's best for the task — not the model your platform vendor has a partnership with.

### 5. Own Your Runtime
HTTP+SSE for production. DirectTransport for testing and RL loops. Run on-prem. Run in the cloud. Run in a hybrid. The transport is a plugin too. The session is yours. The audit trail is yours. The state persistence is yours.

---

## The Protocol in 30 Seconds

```
Agent connects → Handshake negotiates capabilities → Agent uses capability APIs → Host dispatches to plugins → Plugins handle and respond.

handshake/req → "I want tools, memory, learn, subagents"
handshake/resp → "Here's your session. All granted."

tool/call/req → "Read /etc/hostname"
tool/call/resp → {"success": true, "data": {"content": "prod-web-01"}}

memory/store/req → "Remember: user prefers Python"
memory/store/resp → {"stored": 1, "errors": []}

learn/feedback/req → "That tool call was CORRECTIVE. Should have used read_file, not exec."
learn/feedback/resp → {"recorded": 1, "new_score": 0.82}

learn/adapt/req → "Adapt skill routing using UCB1"
learn/adapt/resp → {"updated": [...], "message": "Adapted routing weights using UCB1"}

subagent/spawn/req → "Create a researcher with isolated memory"
subagent/spawn/resp → {"subagent_id": "sub_a1b2c3d4", "status": "READY"}

subagent/delegate/req → "Research quantum computing"
subagent/delegate/resp → {"accepted": true, "status": "RUNNING"}

subagent/merge/req → "Merge researcher + coder results with voting"
subagent/merge/resp → {"merged_result": {...}}
```

80+ message types. 10 capability namespaces. One open protocol.

---

## The World Before A2E

| Problem | Without A2E | With A2E |
|---------|-------------|----------|
| Switch models | Rewrite tool schemas, re-plumb memory API | Change one field in `SubagentConfig.model` |
| Switch memory backend | Rewrite agent code, migrate data, pray | Swap `MemoryPlugin`, agent code unchanged |
| Add RL feedback | Build proprietary eval pipeline | `learn/feedback/req` — standardized, auditable |
| Multi-agent orchestration | Vendor-specific framework, no interop | `SUBAGENT_*` protocol — any host, any agent |
| MCP integration | Vendor-specific MCP client, locked to platform | `mcp/call_tool/req` — standard bridge |
| Compliance/audit | Hope the vendor logs what you need | Every message flows through your audit log |
| Data ownership | Your training data lives in their cloud | Your plugins, your backends, your data |
| Test-time training | Impossible — you can't update weights mid-session | `learn/adapt/req` — real-time adaptation between turns |
| Train-time testing | Separate test harness, no feedback to training loop | `env/step` rewards auto-flow to `learn/feedback` — test IS training |
| RL training data | Manual labeling pipeline, vendor owns the format | `CORRECTIVE` feedback → on-policy advantage; `learn/experience` → off-policy replay |

---

## Get Started

```bash
pip install a2e
```

```python
from a2e.schema import A2EHostConfig
from a2e.core.server.server import A2EServer
from a2e.core.client.client import A2EClient
from a2e.caps.tools.client import ToolAPI
from a2e.caps.memory.client import MemoryAPI
from a2e.caps.learn.client import LearnAPI
from a2e.caps.subagents.client import SubagentClient

# Start the host
config = A2EHostConfig.from_yaml("config.yaml")
server = A2EServer(config)
transport = server.start()

# Connect the agent
client = A2EClient(transport, logger, agent_caps=[
    "tools", "memory", "learning", "subagents"
])
client.connect()

# Use capabilities
tools = ToolAPI(client)
memory = MemoryAPI(client)
learn = LearnAPI(client)
subagents = SubagentClient(client)

# Act
result = tools.call("read_file", {"path": "/etc/hostname"})
memory.remember("user_pref", "Python", tier="episodic")
learn.feedback(polarity="CORRECTIVE", score=-0.5, dimension="CORRECTNESS",
               correction="Use read_file instead of exec")
result = await subagents.run(
    name="researcher", model="claude-3.5-sonnet",
    task_name="market_analysis",
    instruction="Analyze the AI agent framework market",
)
```

**Full documentation**: [A2E Protocol Docs](https://a2e.org)
**Source code**: [github.com/cynepiaadmin/a2e](https://github.com/cynepiaadmin/a2e)
**Protocol spec**: [a2e.org/spec](https://a2e.org/protocol-spec/message-format)

---

## The Thesis

The AI industry is converging on a dangerous equilibrium: model providers commoditize, platform vendors lock in the harness, and enterprises wake up three years later unable to move their agents without rewriting everything.

A2E breaks that equilibrium by making the harness **interchangeable**.

When the protocol is open, the plugins are swappable, and the data is yours — the harness stops being a liability and starts being a **competitive advantage**. You optimize your memory backend for your retrieval patterns. You tune your learning adapter for your feedback distribution. You route your subagents to the models that earn their keep. You own the whole stack.

The agents of 2026 won't be defined by which model they call. They'll be defined by the environment they operate in, the tools they have access to, the memory they accumulate, the feedback they learn from, and the other agents they collaborate with. They'll be defined by whether they can *adapt at test time* — not just whether they passed a benchmark at train time.

The boundary between training and deployment is dissolving. The agents that win will be the ones that learn while they work, test while they train, and improve with every interaction. A2E is the protocol that makes that possible — without locking you into a vendor's cloud, a vendor's format, or a vendor's feedback loop.

That's the harness. And with A2E, **you own it**.

---

*The A2E Protocol is open-source, MIT-licensed, and community-governed. We believe that the infrastructure agents run on should be as open as the internet they were trained on. If you believe that too, [come build with us](https://github.com/cynepiaadmin/a2e).*
