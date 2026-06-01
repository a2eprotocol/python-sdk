# Learning

```text
a2e/caps/learn/protocol.py — MessageType, Feedback, Experience, SkillPerformanceRecord
a2e/caps/learn/plugin.py   — LearnPlugin ABC
a2e/caps/learn/client.py   — LearnAPI
```

The learn capability is what makes A2E agents self-improving. It defines a standard protocol for feedback (human, environment, or self-critique), experience replay (on-policy and off-policy), and adaptation (UCB1, epsilon-greedy, softmax, or custom strategies). Every agent action becomes a training signal; every correction becomes a policy improvement.

## Overview

The **learn** capability provides a feedback-driven learning system — agents can submit feedback signals, record RL experience, trigger skill adaptation, and query performance statistics. It bridges agent evaluation with policy optimization.

## Protocol Messages (8 types)

| Type String | Model | Direction |
|-------------|-------|-----------|
| `learn/feedback/req` | `LearnFeedbackRequest` | Agent → Host |
| `learn/feedback/resp` | `LearnFeedbackResponse` | Host → Agent |
| `learn/experience/req` | `LearnExperienceRequest` | Agent → Host |
| `learn/experience/resp` | `LearnExperienceResponse` | Host → Agent |
| `learn/adapt/req` | `LearnAdaptRequest` | Agent → Host |
| `learn/adapt/resp` | `LearnAdaptResponse` | Host → Agent |
| `learn/stats/req` | `LearnStatsRequest` | Agent → Host |
| `learn/stats/resp` | `LearnStatsResponse` | Host → Agent |

### Feedback Model

**FeedbackPolarity**: `POSITIVE`, `NEGATIVE`, `NEUTRAL`, `CORRECTIVE`

**FeedbackDimension**: `CORRECTNESS`, `HELPFULNESS`, `SAFETY`, `TONE`, `PLAN_QUALITY`

**FeedbackSource**: `HUMAN`, `ENV`, `SELF`

| Field | Type | Description |
|-------|------|-------------|
| `correlation_id` | `str` | Links to the original request |
| `polarity` | `FeedbackPolarity` | Positive/negative/neutral/corrective |
| `score` | `float` | -1.0 to +1.0 |
| `dimension` | `FeedbackDimension` | What aspect is being evaluated |
| `confidence` | `float` | 0-1 confidence in this feedback |
| `comment` | `str` | Free-text explanation |
| `correction` | `str` | Corrected output (for CORRECTIVE polarity) |
| `correction_span` | `dict` | Position of the correction |
| `source` | `FeedbackSource` | Who gave the feedback |
| `annotator_id` | `str` | Annotator identifier |
| `rated_turn` | `RatedTurn` | Associated prompt/response pair |

**Validation**: CORRECTIVE polarity requires `correction` text (enforced by Pydantic `@model_validator`).

**Conversion methods**:
- `to_preference_pair()` → DPO training pair (chosen vs rejected)
- `to_reward_sample()` → Reward model training sample

### Experience Model (RL Replay)

```python
Experience(
    state: dict,        # Current state
    action: dict,       # Action taken
    reward: float,      # Reward received
    next_state: dict,   # Resulting state
    done: bool          # Terminal flag
)
```

### SkillPerformanceRecord

Rolling per-skill/tool performance stats:

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Skill or tool name |
| `calls_total` | `int` | Total invocations |
| `calls_success` | `int` | Successful calls |
| `calls_failed` | `int` | Failed calls |
| `avg_duration_ms` | `float` | Average execution time |
| `avg_score` | `float` | Average feedback score |
| `p95_duration_ms` | `float` | P95 latency |

### Adaptation Strategies

| Strategy | Description |
|----------|-------------|
| `ucb1` | Upper Confidence Bound — explore/exploit based on confidence intervals |
| `epsilon_greedy` | Random exploration with epsilon probability |
| `softmax` | Boltzmann exploration over value estimates |
| `custom` | User-defined strategy |

## LearnPlugin ABC

```python
class LearnPlugin(A2EPlugin):
    name = "learn"
    priority = 5

    @abstractmethod
    def _record_feedback(self, feedbacks) -> tuple[int, dict]: ...

    @abstractmethod
    def _store_experiences(self, experiences) -> int: ...

    @abstractmethod
    def _adapt(self, skill_name, strategy) -> list[SkillPerformanceRecord]: ...

    @abstractmethod
    def _get_stats(self, skill_name, tool_name) -> dict: ...
```

## LearnAPI (Client)

```python
from a2e.caps.learn.client import LearnAPI

learn = LearnAPI(client)

# Submit feedback
resp = learn.feedback(
    polarity="POSITIVE",
    score=0.9,
    dimension="CORRECTNESS",
    confidence=0.95,
    prompt="What is 2+2?",
    response="4",
    source="HUMAN",
    comment="Correct answer"
)

# Record RL experience
count = learn.experience([
    {"state": {"count": 0}, "action": {"type": "inc"}, "reward": 1.0,
     "next_state": {"count": 1}, "done": False}
])

# Trigger adaptation
records = learn.adapt(skill_name="my_skill", strategy="ucb1")

# Query stats
skills, tools = learn.stats(skill_name="my_skill")

# Convenience: send scalar reward
learn.reward(skill_name="my_skill", value=1.0, correlation_id="req_123")
```
