# Learning

The learn capability is what makes A2E agents self-improving. It defines a standard protocol for feedback (human, environment, or self-critique), experience replay (on-policy and off-policy), and adaptation (UCB1, epsilon-greedy, softmax, or custom strategies). Every agent action becomes a training signal; every correction becomes a policy improvement.

## Overview

The **learn** capability provides a feedback-driven learning system — agents can submit feedback signals, record RL experience, trigger component adaptation, and query performance statistics. It bridges agent evaluation with policy optimization.

## Protocol Messages (18 types)

|| Type String | Model | Direction |
||-------------|-------|-----------|
|| `learn/feedback/req` | `LearnFeedbackRequest` | Agent → Host |
|| `learn/feedback/resp` | `LearnFeedbackResponse` | Host → Agent |
|| `learn/experience/req` | `LearnExperienceRequest` | Agent → Host |
|| `learn/experience/resp` | `LearnExperienceResponse` | Host → Agent |
|| `learn/adapt/req` | `LearnAdaptRequest` | Agent → Host |
|| `learn/adapt/resp` | `LearnAdaptResponse` | Host → Agent |
|| `learn/stats/req` | `LearnStatsRequest` | Agent → Host |
|| `learn/stats/resp` | `LearnStatsResponse` | Host → Agent |
|| `learn/refinement/plan/req` | `LearnRefinementPlanRequest` | Agent → Host |
|| `learn/refinement/plan/resp` | `LearnRefinementPlanResponse` | Host → Agent |
|| `learn/refinement/apply/req` | `LearnRefinementApplyRequest` | Agent → Host |
|| `learn/refinement/apply/resp` | `LearnRefinementApplyResponse` | Host → Agent |
|| `learn/refinement/rollback/req` | `LearnRefinementRollbackRequest` | Agent → Host |
|| `learn/refinement/rollback/resp` | `LearnRefinementRollbackResponse` | Host → Agent |
|| `learn/refinement/review/req` | `LearnRefinementReviewRequest` | Agent → Host |
|| `learn/refinement/review/resp` | `LearnRefinementReviewResponse` | Host → Agent |
|| `learn/refinement/history/req` | `LearnRefinementHistoryRequest` | Agent → Host |
|| `learn/refinement/history/resp` | `LearnRefinementHistoryResponse` | Host → Agent |

### Feedback Model

**FeedbackPolarity**: `POSITIVE`, `NEGATIVE`, `NEUTRAL`, `CORRECTIVE`

**FeedbackDimension**: `CORRECTNESS`, `HELPFULNESS`, `SAFETY`, `TONE`, `PLAN_QUALITY`

**FeedbackSource**: `HUMAN`, `ENV`, `SELF`

|| Field | Type | Description |
||-------|------|-------------|
|| `correlation_id` | `str` | Links to the original request |
|| `polarity` | `FeedbackPolarity` | Positive/negative/neutral/corrective |
|| `score` | `float` | -1.0 to +1.0 |
|| `dimension` | `FeedbackDimension` | What aspect is being evaluated |
|| `confidence` | `float` | 0-1 confidence in this feedback |
|| `comment` | `str` | Free-text explanation |
|| `correction` | `str` | Corrected output (for CORRECTIVE polarity) |
|| `correction_span` | `dict` | Position of the correction |
|| `source` | `FeedbackSource` | Who gave the feedback |
|| `annotator_id` | `str` | Annotator identifier |
|| `rated_turn` | `RatedTurn` | Associated prompt/response pair |

**Validation**: CORRECTIVE polarity requires `correction` text (enforced by Pydantic `@model_validator`).

**Conversion methods**:
- `to_preference_pair()` → DPO training pair (chosen vs rejected)
- `to_reward_sample()` → Reward model training sample

### Experience Model (RL Replay)

```python
Experience(
    state: dict,        # Current state
    action: dict,       # Action taken (keyed by component_name)
    reward: float,      # Reward received
    next_state: dict,   # Resulting state
    done: bool          # Terminal flag
)
```

### ComponentPerformanceRecord

Rolling per-component performance stats (replaces `SkillPerformanceRecord`):

|| Field | Type | Description |
||-------|------|-------------|
|| `component_name` | `str` | Component identifier (skill, tool, subagent, toolkit) |
|| `calls_total` | `int` | Total invocations |
|| `calls_success` | `int` | Successful calls |
|| `calls_failed` | `int` | Failed calls |
|| `avg_duration_ms` | `float` | Average execution time |
|| `avg_score` | `float` | Average feedback score |
|| `p95_duration_ms` | `float` | P95 latency |

### Adaptation Strategies

|| Strategy | Description |
||----------|-------------|
|| `ucb1` | Upper Confidence Bound — explore/exploit based on confidence intervals |
|| `epsilon_greedy` | Random exploration with epsilon probability |
|| `softmax` | Boltzmann exploration over value estimates |
|| `custom` | User-defined strategy |

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
    def _adapt(self, component_name, strategy) -> list[ComponentPerformanceRecord]: ...

    @abstractmethod
    def _get_stats(self, component_name, tool_name) -> dict: ...
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
    {"state": {"count": 0}, "action": {"component_name": "inc"}, "reward": 1.0,
     "next_state": {"count": 1}, "done": False}
])

# Fire-and-forget adaptation (server handles plan → review → apply → stats)
records = learn.adapt(component_name="", strategy="ppo")

# Unified refinement interface — one method, five modes
plan = learn.refine(component_name="my-tool", action="plan")
review = learn.refine(component_name="my-tool", action="review", proposal=plan["proposals"][0])
result = learn.refine(component_name="my-tool", action="apply", proposal=plan["proposals"][0])
result = learn.refine(component_name="my-tool", action="rollback", refinement_id="ref-123")
history = learn.refine(component_name="my-tool", action="history")

# Query stats
records = learn.stats(component_name="my-tool")

# Convenience: send scalar reward
learn.reward(component_name="my-tool", value=1.0, correlation_id="req_123")
```

## adapt() vs refine() — When to Use Which

| Aspect | `adapt()` | `refine(action=...)` |
|---|---|---|
| **Granularity** | Batch — plans, reviews, and applies all proposals in one call | Per-proposal — plan, review, apply, rollback individually |
| **Control flow** | Fire-and-forget | Step-by-step with decision points |
| **Per-proposal inspection** | No — applies all approved proposals automatically | Yes — you decide accept/reject per proposal |
| **Rollback** | No — once applied, changes are permanent | Yes — `action="rollback"` undoes a bad apply |
| **History** | No — no way to query past refinements | Yes — `action="history"` loads the full refinement log |
| **Best for** | Simple auto-optimization with no human oversight | Human-in-the-loop, safety-critical, or auditable workflows |

### Rule of thumb

- **`adapt()`** = "optimize everything, I trust the system"
- **`refine(action="plan")`** = "show me the proposals"
- **`refine(action="review")`** = "let me gate each proposal"
- **`refine(action="apply")`** = "apply this specific proposal"
- **`refine(action="rollback")`** = "undo the last apply"
- **`refine(action="history")`** = "show me what changed"

### See also

- [Learning protocol messages](#protocol-messages-18-types) — the full request/response reference for the learn capability, including fields, directions, and wire examples
- [Environment capability](/capabilities/env) — how agent actions are scored and turned into rewards that feed the learn experience buffer
- [Protocol: Learning](/protocol-spec/learn) — the wire-level message definitions for learn/feedback, learn/experience, and learn/adapt

The learn capability is the feedback engine behind A2E's self-improvement loop: environment or human feedback is recorded as experience, then `adapt()` or `refine()` turns that experience into policy updates you can gate, apply, and roll back.
