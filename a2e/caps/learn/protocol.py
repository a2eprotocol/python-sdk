# ═════════════════════════════════════════════════════════════════════════════
# ── NAMESPACE: learn/*  ──────────────────────────────────────────────────────
#
# Agent learning subsystem.
#
# Three primitives:
#   feedback    — human or environment reward signal attached to a turn
#   experience  — store a (state, action, reward, next_state) tuple for replay
#   adapt       — request that the host updates skill hyperparams based on
#                 accumulated experience (online fine-tuning hook)
# ═════════════════════════════════════════════════════════════════════════════
import uuid
import time
from enum import Enum
from typing import Optional, Any, List
from pydantic import BaseModel, Field, model_validator
from a2e.caps.base.protocol import A2EMessage


class MessageType(str, Enum):
    LEARN_FEEDBACK_REQ = "learn/feedback/req"
    LEARN_FEEDBACK_RESP = "learn/feedback/resp"
    LEARN_EXPERIENCE_REQ = "learn/experience/req"
    LEARN_EXPERIENCE_RESP = "learn/experience/resp"
    LEARN_ADAPT_REQ = "learn/adapt/req"
    LEARN_ADAPT_RESP = "learn/adapt/resp"
    LEARN_STATS_REQ = "learn/stats/req"
    LEARN_STATS_RESP = "learn/stats/resp"
    LEARN_REFINEMENT_PLAN_REQ = "learn/refinement/plan/req"
    LEARN_REFINEMENT_PLAN_RESP = "learn/refinement/plan/resp"
    LEARN_REFINEMENT_APPLY_REQ = "learn/refinement/apply/req"
    LEARN_REFINEMENT_APPLY_RESP = "learn/refinement/apply/resp"
    LEARN_REFINEMENT_ROLLBACK_REQ = "learn/refinement/rollback/req"
    LEARN_REFINEMENT_ROLLBACK_RESP = "learn/refinement/rollback/resp"
    LEARN_REFINEMENT_REVIEW_REQ = "learn/refinement/review/req"
    LEARN_REFINEMENT_REVIEW_RESP = "learn/refinement/review/resp"
    LEARN_REFINEMENT_HISTORY_REQ = "learn/refinement/history/req"
    LEARN_REFINEMENT_HISTORY_RESP = "learn/refinement/history/resp"


class FeedbackPolarity(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    CORRECTIVE = "corrective"   # "you should have done X instead"


class FeedbackDimension(str, Enum):
    """Which axis is being rated. Lets you train dimension-specific reward heads."""
    CORRECTNESS = "correctness"
    HELPFULNESS = "helpfulness"
    SAFETY = "safety"
    TONE = "tone"
    PLAN_QUALITY = "plan_quality"


class FeedbackSource(str, Enum):
    HUMAN = "human"
    ENV = "env"       # environment signal (test pass/fail, tool error, etc.)
    SELF = "self"      # model self-critique


class AdaptStrategy(str, Enum):
    """Adaptation strategy for component routing optimization."""

    PPO = "ppo"              # Proximal Policy Optimization — policy gradient with clipping
    UCB1 = "ucb1"            # Upper Confidence Bound — explore/exploit based on confidence intervals
    EPSILON_GREEDY = "epsilon_greedy"  # Random exploration with epsilon probability
    SOFTMAX = "softmax"      # Boltzmann exploration over value estimates
    CUSTOM = "custom"        # User-defined strategy


# ── The turn that was rated ──────────────────────────────────────────────────

class RatedTurn(BaseModel):
    """Captures enough context to reconstruct a training pair later."""
    prompt: str                  # full prompt sent to the model/skill
    response: str                # the response that was rated
    model: str           # e.g. "agent-v2.3.1"
    environment: Optional[Any] = None
    version: Optional[str] = None   # e.g. "sql-skill-v1.0"


class Feedback(BaseModel):
    """A single feedback signal attached to an agent turn or skill call."""

    # ---- Identity ----
    feedback_id: str = Field(default_factory=lambda: f"b_{time.time_ns()}")
    correlation_id: str = ""  # ties to agent turn
    session_id: str = ""

    # --- What was rated ----
    rated_turn: Optional[RatedTurn]

    # ---- signal -----
    polarity: FeedbackPolarity  # FeedbackPolarity value
    score: float = 0.0   # normalised −1.0 … +1.0
    dimension: FeedbackDimension = FeedbackDimension.HELPFULNESS
    confidence: float = 1.0

    # ---- correlation payload ----
    comment: str = ""
    correction: str = ""    # filled for CORRECTIVE polarity
    correction_span: Optional[tuple[int, int]] = None

    # ---- Provenance ---
    source: FeedbackSource = FeedbackSource.HUMAN
    annotator_id: str = ""
    ts: float = Field(default_factory=time.time)

    # --- Validation ---
    @model_validator(mode="after")
    def correction_requires_text(self) -> "Feedback":
        if self.polarity == FeedbackPolarity.CORRECTIVE and not self.correction:
            raise ValueError("CORRECTIVE feedback must include a correction string")
        return self

    def to_preference_pair(self) -> Optional[dict]:
        if (
            self.polarity != FeedbackPolarity.CORRECTIVE
            or not self.rated_turn
            or not self.correction
        ):
            return None

        env = self.rated_turn.environment
        return {
            "prompt": self.rated_turn.prompt,
            "chosen": self.correction,
            "rejected": self.rated_turn.response,
            "dimension": self.dimension.value,
            "model_version": self.rated_turn.model_version,
            "confidence": self.confidence,
            # Environment context — useful for slicing DPO data by skill/agent
            # "agent": env.agent_name,
            # "skills_used": env.component_names,
            # "had_failures": env.had_failures,
        }

    def to_reward_sample(self) -> Optional[dict]:
        if not self.rated_turn:
            return None

        env = self.rated_turn.environment

        return {
            "prompt": self.rated_turn.prompt,
            "response": self.rated_turn.response,
            "score": self.score,
            "dimension": self.dimension.value,
            "weight": self.confidence,
            "source": self.source.value,
            # Environment context — reward model can condition on these
            # "agent": env.agent_name,
            # "skills_used": env.component_names,
            # "had_failures": env.had_failures,
            # "deployment": env.deployment,
        }


class LearnFeedbackRequest(A2EMessage):
    """Agent (or external trainer) → Host.  Submit feedback signals."""
    type: MessageType = MessageType.LEARN_FEEDBACK_REQ
    feedbacks: List[Feedback]


class LearnFeedbackResponse(A2EMessage):
    type: MessageType = MessageType.LEARN_FEEDBACK_RESP
    req_id: str = ""
    recorded: int = 0
    new_score: float | None = None   # updated running skill score if available


class Experience(BaseModel):
    """
    A (state, action, reward, next_state, done) tuple for RL-style replay.

    `state`      — serialised agent context before the action
    `action`     — { component_name / tool_name, input }
    `reward`     — scalar reward from the environment
    `next_state` — serialised agent context after the action
    `done`       — whether the episode ended
    """
    experience_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    state: dict = Field(default_factory=dict)
    action: dict = Field(default_factory=dict)
    reward: float = 0.0
    next_state: dict = Field(default_factory=dict)
    done: bool = False
    episode_id: str = ""
    step: int = 0
    ts: float = Field(default_factory=time.time)


class LearnExperienceRequest(A2EMessage):
    """Agent → Host.  Store one or more experience tuples for later replay."""
    type: MessageType = MessageType.LEARN_EXPERIENCE_REQ
    experiences: list[Experience] = Field(default_factory=list)


class LearnExperienceResponse(A2EMessage):
    type: MessageType = MessageType.LEARN_EXPERIENCE_RESP
    req_id: str = ""
    stored: int = 0


class ComponentPerformanceRecord(BaseModel):
    """
    Rolling performance stats tracked per skill, used for adaptive routing.
    The host maintains this; agents can query or reset it.
    """
    component_name: str
    calls_total: int = 0
    calls_success: int = 0
    calls_failed: int = 0
    avg_duration_ms: float = 0.0
    avg_score: float = 0.0   # mean feedback score (−1…+1)
    last_called: float = 0.0
    p95_duration_ms: float = 0.0


class LearnAdaptRequest(A2EMessage):
    """
    Agent → Host.  Ask the host to update routing weights based on
    accumulated feedback and experiences.

    `component_name`  — empty = adapt all components (skills, tools, subagents)
    `strategy`        — adaptation strategy (default: PPO)
    """
    type: MessageType = MessageType.LEARN_ADAPT_REQ
    component_name: str = ""
    strategy: AdaptStrategy = AdaptStrategy.PPO


class LearnAdaptResponse(A2EMessage):
    type: MessageType = MessageType.LEARN_ADAPT_RESP
    req_id: str = ""
    updated: list[dict] = Field(default_factory=list)  # list[ComponentPerformanceRecord]
    message: str = ""


class LearnStatsRequest(A2EMessage):
    """Agent → Host.  Query performance stats for a component."""
    type: MessageType = MessageType.LEARN_STATS_REQ
    component_name: str = ""   # empty = all components


class LearnStatsResponse(A2EMessage):
    type: MessageType = MessageType.LEARN_STATS_RESP
    req_id: str = ""
    components: list[dict] = Field(default_factory=list)  # list[ComponentPerformanceRecord]


# ── Refinement request/response types ──────────────────────

class LearnRefinementPlanRequest(A2EMessage):
    """Agent → Host.  Request a refinement plan from accumulated feedback."""
    type: MessageType = MessageType.LEARN_REFINEMENT_PLAN_REQ
    component_name: str = ""
    scope: str = "local"


class LearnRefinementPlanResponse(A2EMessage):
    type: MessageType = MessageType.LEARN_REFINEMENT_PLAN_RESP
    req_id: str = ""
    plan_id: str = ""
    proposals: list[dict] = Field(default_factory=list)
    status: str = ""


class LearnRefinementApplyRequest(A2EMessage):
    """Agent → Host.  Apply a refinement proposal."""
    type: MessageType = MessageType.LEARN_REFINEMENT_APPLY_REQ
    proposal: dict = Field(default_factory=dict)


class LearnRefinementApplyResponse(A2EMessage):
    type: MessageType = MessageType.LEARN_REFINEMENT_APPLY_RESP
    req_id: str = ""
    refinement_id: str = ""
    applied_edits: int = 0
    failed_edits: int = 0
    rollback_available: bool = False
    error: str = ""


class LearnRefinementRollbackRequest(A2EMessage):
    """Agent → Host.  Rollback a previously applied refinement."""
    type: MessageType = MessageType.LEARN_REFINEMENT_ROLLBACK_REQ
    refinement_id: str = ""


class LearnRefinementRollbackResponse(A2EMessage):
    type: MessageType = MessageType.LEARN_REFINEMENT_ROLLBACK_RESP
    req_id: str = ""
    refinement_id: str = ""
    rolled_back: bool = False
    error: str = ""


class LearnRefinementReviewRequest(A2EMessage):
    """Agent → Host.  Auto-review a refinement proposal."""
    type: MessageType = MessageType.LEARN_REFINEMENT_REVIEW_REQ
    proposal: dict = Field(default_factory=dict)


class LearnRefinementReviewResponse(A2EMessage):
    type: MessageType = MessageType.LEARN_REFINEMENT_REVIEW_RESP
    req_id: str = ""
    approved: bool = False
    confidence_adjusted: float = 0.0
    reasons: list[str] = Field(default_factory=list)
    risk_level: str = "low"


class LearnRefinementHistoryRequest(A2EMessage):
    """Agent → Host.  Load refinement history."""
    type: MessageType = MessageType.LEARN_REFINEMENT_HISTORY_REQ


class LearnRefinementHistoryResponse(A2EMessage):
    type: MessageType = MessageType.LEARN_REFINEMENT_HISTORY_RESP
    req_id: str = ""
    entries: list[dict] = Field(default_factory=list)


# Learn message types are also valid in A2E
LEARN_TYPE_MAP = {
    MessageType.LEARN_FEEDBACK_REQ: LearnFeedbackRequest,
    MessageType.LEARN_FEEDBACK_RESP: LearnFeedbackResponse,
    MessageType.LEARN_EXPERIENCE_REQ: LearnExperienceRequest,
    MessageType.LEARN_EXPERIENCE_RESP: LearnExperienceResponse,
    MessageType.LEARN_ADAPT_REQ: LearnAdaptRequest,
    MessageType.LEARN_ADAPT_RESP: LearnAdaptResponse,
    MessageType.LEARN_STATS_REQ: LearnStatsRequest,
    MessageType.LEARN_STATS_RESP: LearnStatsResponse,
    MessageType.LEARN_REFINEMENT_PLAN_REQ: LearnRefinementPlanRequest,
    MessageType.LEARN_REFINEMENT_PLAN_RESP: LearnRefinementPlanResponse,
    MessageType.LEARN_REFINEMENT_APPLY_REQ: LearnRefinementApplyRequest,
    MessageType.LEARN_REFINEMENT_APPLY_RESP: LearnRefinementApplyResponse,
    MessageType.LEARN_REFINEMENT_ROLLBACK_REQ: LearnRefinementRollbackRequest,
    MessageType.LEARN_REFINEMENT_ROLLBACK_RESP: LearnRefinementRollbackResponse,
    MessageType.LEARN_REFINEMENT_REVIEW_REQ: LearnRefinementReviewRequest,
    MessageType.LEARN_REFINEMENT_REVIEW_RESP: LearnRefinementReviewResponse,
    MessageType.LEARN_REFINEMENT_HISTORY_REQ: LearnRefinementHistoryRequest,
    MessageType.LEARN_REFINEMENT_HISTORY_RESP: LearnRefinementHistoryResponse,
}
