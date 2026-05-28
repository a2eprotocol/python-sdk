# ═════════════════════════════════════════════════════════════════════════════
# ── NAMESPACE: chain/*  ──────────────────────────────────────────────────────
#
# Multi-step skill / tool pipelines declared as a DAG.
# The host executes the chain, passing outputs as inputs to downstream nodes.
#
# Chain node types:
#   skill   — invoke a skill by name
#   tool    — call a native tool
#   branch  — conditional fork (if/else on a JMESPath expression)
#   map     — fan-out: apply one node to a list of items in parallel
# ═════════════════════════════════════════════════════════════════════════════
import uuid
from typing import Any
from enum import Enum
from pydantic import BaseModel, Field
from a2e.caps.base.protocol import (
    A2EMessage,
    A2EEvent,
)


class MessageType(str, Enum):
    CHAIN_REQ = "chain/req"
    CHAIN_RESP = "chain/resp"
    CHAIN_EVENT = "chain/event"


class ChainErrorCode(str, Enum):
    # Chain-specific
    CHAIN_CYCLE = "chain_cycle"       # DAG contains a cycle
    CHAIN_NODE_ERROR = "chain_node_error"


class ChainNode(BaseModel):
    """Single node in an execution chain."""
    node_id: str
    kind: str        # "skill" | "tool" | "branch" | "map"
    name: str = ""   # skill_name or tool_name
    input: dict = Field(default_factory=dict)
    # Input template: keys are node input Fields;
    # values are JMESPath expressions
    # evaluated against the chain context
    # (prior node outputs + initial input).
    input_map: dict = Field(default_factory=dict)
    # Routing for branch nodes
    condition: str = ""   # JMESPath boolean expression
    true_node: str = ""   # node_id to run if condition is True
    false_node: str = ""   # node_id to run if condition is False
    # Fan-out for map nodes
    items_path: str = ""   # JMESPath → list to iterate
    map_node: str = ""   # node_id to apply to each item
    # DAG edges
    next_node: str = ""   # default successor node_id
    on_error: str = "abort"   # "abort" | "skip" | "<node_id>"


class ChainRequest(A2EMessage):
    """
    Agent → Host.  Execute a skill/tool chain.

    `nodes`        — list of ChainNode dicts (must form a valid DAG)
    `entry_node`   — node_id of the first node to execute
    `initial_input`— seed input available to all nodes as `$.input`
    `streaming`    — emit ChainEvent messages during execution
    """
    type: str = "chain/req"
    session_id: str = ""
    chain_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    nodes: list[dict] = Field(default_factory=list)
    entry_node: str = ""
    initial_input: dict = Field(default_factory=dict)
    correlation_id: str = ""
    streaming: bool = True
    timeout: int = 300


class ChainEvent(A2EEvent):
    """
    Host → Agent.  Progress update during chain execution.

    `node_id`  — which node just finished or started
    `phase`    — "start" | "done" | "skip" | "error"
    `output`   — node output (populated when phase="done")
    """
    type: str = "chain/event"
    node_id: str = ""
    phase: str = "start"
    output: Any = None
    error: str = ""


class ChainResponse(A2EMessage):
    """Host → Agent.  Final result of the full chain."""
    type: str = "chain/resp"
    req_id: str = ""
    chain_id: str = ""
    success: bool = False
    outputs: dict = Field(default_factory=dict)   # node_id → output
    final_output: Any = None   # output of the terminal node
    duration_ms: int = 0
    nodes_run: int = 0
    error: dict | None = None


# Chain message types are also valid in A2E
CHAIN_TYPE_MAP = {
    MessageType.CHAIN_REQ: ChainRequest,
    MessageType.CHAIN_EVENT: ChainEvent,
    MessageType.CHAIN_RESP: ChainResponse,
}
