# ═════════════════════════════════════════════════════════════════════════════
# ── NAMESPACE: env/*  ───────────────────────────────────────────────────────
#
# RL Environment interaction subsystem.
#
# Defines the step-wise interaction loop between Agent and Environment.
#
# Core primitives:
#   reset   — Initialize a new episode and return initial state
#   step    — Execute an action in the environment and receive
#             (next_state, reward, done, info)
#   observe — Retrieve current environment state without acting
#
# Extended primitives:
#   close   — Terminate an episode early
#   spaces  — Discover action/state space definitions
#   render  — Retrieve visual or multimodal representation of state
#   plan    — (Optional) Get environment-suggested affordances/actions
#   batch_step — (Optional) Execute multiple steps in parallel
#
# Notes:
#   - Each env/step interaction can be automatically recorded as an
#     (state, action, reward, next_state, done) tuple in the ExperienceBuffer.
#   - Reward signals can be forwarded to the learning subsystem
#     (learn/*) for routing and adaptation.
#   - Enables integration with RL-style training loops, simulations,
#     and CUA/browser environments.
#
# ═════════════════════════════════════════════════════════════════════════════
import time
import uuid
from pydantic import BaseModel, Field, ConfigDict
from enum import Enum
from typing import Optional, List, Dict, Any, Literal
from a2e.caps.base.protocol import (
    A2EMessage,
)


class MessageType(str, Enum):
    ENV_OBSERVE_REQ = "env/observe/req"
    ENV_OBSERVE_RESP = "env/observe/resp"

    ENV_RESET_REQ = "env/reset/req"
    ENV_RESET_RESP = "env/reset/resp"

    ENV_STEP_REQ = "env/step/req"
    ENV_STEP_RESP = "env/step/resp"

    ENV_CLOSE_REQ = "env/close/req"
    ENV_CLOSE_RESP = "env/close/resp"

    ENV_SPACE_REQ = "env/space/req"
    ENV_SPACE_RESP = "env/space/resp"

    ENV_STATE_PUSH = "env/state/push"

    ENV_RENDER_REQ = "env/render/req"
    ENV_RENDER_RESP = "env/render/resp"

    ENV_PLAN_REQ = "env/plan/resp"
    ENV_PLAN_RESP = "env/plan/resp"

    ENV_BATCH_STEP_REQ = "env/batch_step/req"
    ENV_BATCH_STEP_RESP = "env/batch_step/resp"


class EnvErrorCode(str, Enum):
    RUNTIME_ERROR = "runtime_error"
    UNKNOWN_ACTION = "unknown_action"
    RESET_DENIED = "reset_denied"


class EnvAction(BaseModel):
    action_type: str
    payload: Dict[str, Any] = Field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Additional metadata for the action"
    )


class EnvState(BaseModel):
    model_config = ConfigDict(
        extra="allow",  # Allow extra fields for flexibility
        validate_assignment=True,
        arbitrary_types_allowed=True,
    )


class EnvObservation(BaseModel):
    episode_id: str
    step_num: int
    state: EnvState
    done: bool = False
    truncated: bool = False
    reward: Optional[float] = 0.0
    created_at: float = Field(default_factory=time.time)
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Additional metadata for the observation"
    )
    model_config = ConfigDict(
        extra="allow",  # Allow extra fields for flexibility
        validate_assignment=True,
        arbitrary_types_allowed=True,
    )


# ---------------------------------------------------------------------------
# INTERNAL EPISODE STATE
# ---------------------------------------------------------------------------
class _Episode(BaseModel):
    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()))
    state: EnvState
    done: bool = False
    step_num: int = 0
    created_at: float = Field(default_factory=time.time)


# ---------------------------------------------------------------------------
# ENV RESET
# ---------------------------------------------------------------------------
class EnvResetRequest(A2EMessage):
    type: MessageType = MessageType.ENV_RESET_REQ

    env_name: str
    seed: Optional[int] = None
    options: Dict[str, Any] = Field(default_factory=dict)


class EnvResetResponse(A2EMessage):
    type: MessageType = MessageType.ENV_RESET_RESP

    req_id: str = ""
    obs: EnvObservation


class EnvEvent(BaseModel):
    # --- identity ---
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str  # use Literal in subclasses

    # --- trajectory context ---
    episode_id: str
    step_id: int

    # --- linkage ---
    action_id: Optional[str] = None  # tie to EnvAction

    # --- payload ---
    payload: Dict[str, Any] = Field(default_factory=dict)

    # --- timing ---
    timestamp: float = Field(default_factory=lambda: time.time())

    # --- metadata ---
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EnvStatePush(A2EMessage):
    """
    Host → Agent (server-initiated).

    Pushes an incremental environment state update to the agent.
    This is only emitted if the agent has negotiated the "env_push"
    capability during session setup.

    The `delta` field contains a sparse diff (only changed fields),
    not a full state snapshot.

    Typical use cases:
      - async tool completion
      - external world changes (file system, browser DOM, etc.)
      - long-running process updates
      - safety / system signals (OOM, timeout, etc.)
    """

    type: MessageType = MessageType.ENV_STATE_PUSH

    # ---- trajectory lineage ----
    episode_id: str
    step_id: int
    action_id: Optional[str] = None

    # ---- event semantics ----
    event_type: str  # Observation, tool_result, status, error
    reason: str = ""                        # e.g. "proc_exit", "oom_warning"

    # State update
    delta: Dict[str, Any] = Field(default_factory=dict)

    # Reward info
    reward: Optional[float] = None          # optional reward signal
    reward_info: Optional[Dict] = Field(default_factory=dict)

    # optional structured hints for agent policies
    terminal: bool = False                  # marks episode termination

    # --- timing ---
    ts: float = Field(default_factory=time.time)


# ---------------------------------------------------------------------------
# ENV STEP (CORE RL PRIMITIVE)
# ---------------------------------------------------------------------------
class EnvStepRequest(A2EMessage):
    type: MessageType = MessageType.ENV_STEP_REQ

    episode_id: str
    action: Dict[str, Any]


class EnvStepResponse(A2EMessage):
    type: MessageType = MessageType.ENV_STEP_RESP

    req_id: str = ""
    obs: EnvObservation


# ---------------------------------------------------------------------------
# ENV OBSERVE (READ-ONLY STATE)
# ---------------------------------------------------------------------------
class EnvObserveRequest(A2EMessage):
    type: MessageType = MessageType.ENV_OBSERVE_REQ

    episode_id: str


class EnvObserveResponse(A2EMessage):
    type: MessageType = MessageType.ENV_OBSERVE_RESP
    req_id: str = ""

    obs: EnvObservation


# ---------------------------------------------------------------------------
# ENV CLOSE (END EPISODE)
# ---------------------------------------------------------------------------
class EnvCloseRequest(A2EMessage):
    type: MessageType = MessageType.ENV_CLOSE_REQ

    episode_id: str


class EnvCloseResponse(A2EMessage):
    type: MessageType = MessageType.ENV_CLOSE_RESP

    closed: bool = True


# ---------------------------------------------------------------------------
# ENV SPACES (ACTION / STATE DISCOVERY)
# ---------------------------------------------------------------------------
class EnvSpacesRequest(A2EMessage):
    type: MessageType = MessageType.ENV_SPACE_REQ

    env_name: str


class EnvSpacesResponse(A2EMessage):
    type: MessageType = MessageType.ENV_SPACE_RESP

    action_space: Dict[str, Any]
    state_schema: Dict[str, Any]


# ---------------------------------------------------------------------------
# ENV RENDER (OPTIONAL MULTIMODAL SUPPORT)
# ---------------------------------------------------------------------------
class EnvRenderRequest(A2EMessage):
    type: MessageType = MessageType.ENV_RENDER_REQ

    episode_id: str
    mode: Optional[str] = "screenshot"   # screenshot | rgb_array | text


class EnvRenderResponse(A2EMessage):
    type: MessageType = MessageType.ENV_RENDER_RESP

    render: Any   # bytes, base64, or structured payload


# ---------------------------------------------------------------------------
# ENV PLAN (OPTIONAL AFFORDANCE DISCOVERY)
# ---------------------------------------------------------------------------
class EnvPlanRequest(A2EMessage):
    type: MessageType = MessageType.ENV_PLAN_REQ

    episode_id: Optional[str] = None
    state: Optional[Dict[str, Any]] = None


class EnvPlanResponse(A2EMessage):
    type: MessageType = MessageType.ENV_PLAN_RESP

    suggested_actions: List[Dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# OPTIONAL: BATCH STEP (FOR SCALING RL)
# ---------------------------------------------------------------------------
class EnvBatchStepRequest(A2EMessage):
    type: MessageType = MessageType.ENV_BATCH_STEP_REQ

    episode_ids: List[str]
    actions: List[Dict[str, Any]]


class EnvBatchStepResponse(A2EMessage):
    type: MessageType = MessageType.ENV_BATCH_STEP_RESP
    type: Literal["env/batch_step/resp"] = "env/batch_step/resp"

    results: List[EnvStepResponse]


# ---------------------------------------------------------------------------
# TYPE REGISTRY (plug into your decoder)
# ---------------------------------------------------------------------------
ENV_TYPE_MAP = {
    # reset
    MessageType.ENV_RESET_REQ: EnvResetRequest,
    MessageType.ENV_RESET_RESP: EnvResetResponse,

    # step
    MessageType.ENV_STEP_REQ: EnvStepRequest,
    MessageType.ENV_STEP_RESP: EnvStepResponse,

    # observe
    MessageType.ENV_OBSERVE_REQ: EnvObserveRequest,
    MessageType.ENV_OBSERVE_RESP: EnvObserveResponse,

    # close
    MessageType.ENV_CLOSE_REQ: EnvCloseRequest,
    MessageType.ENV_CLOSE_RESP: EnvCloseResponse,

    # spaces
    MessageType.ENV_SPACE_REQ: EnvSpacesRequest,
    MessageType.ENV_SPACE_RESP: EnvSpacesResponse,

    # render
    MessageType.ENV_RENDER_REQ: EnvRenderRequest,
    MessageType.ENV_RENDER_RESP: EnvRenderResponse,

    # plan
    MessageType.ENV_PLAN_REQ: EnvPlanRequest,
    MessageType.ENV_PLAN_RESP: EnvPlanResponse,

    # batch
    MessageType.ENV_BATCH_STEP_REQ: EnvBatchStepRequest,
    MessageType.ENV_BATCH_STEP_RESP: EnvBatchStepResponse,

    # state push
    MessageType.ENV_STATE_PUSH: EnvStatePush
}
