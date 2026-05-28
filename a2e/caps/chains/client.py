import uuid
from typing import Any, Callable
from pydantic import BaseModel, Field
from a2e.core.client import (
    A2EClient,
    A2EClientError
)
from a2e.caps.base.protocol import (
    A2EError
)
from a2e.caps.chains.protocol import (
    ChainEvent,
    ChainRequest,
    ChainResponse,
    ChainNode
)


ChainEventCallback = Callable[[ChainEvent], None]


class ChainResult(BaseModel):
    success: bool
    chain_id: str
    final_output: Any
    outputs: dict = Field(default_factory=dict)
    duration_ms: int = 0
    nodes_run: int = 0
    error: dict | None = None
    events: list[ChainEvent] = Field(default_factory=list)


class ChainsAPI:
    def __init__(self, client: A2EClient):
        self._c = client

    def run(
        self,
        nodes: list[ChainNode] | list[dict],
        entry_node: str,
        initial_input: dict = None,
        *,
        streaming: bool = True,
        on_event: ChainEventCallback = None,
        correlation_id: str = "",
        timeout: int = 300,
    ) -> ChainResult:
        raw_nodes = [n if isinstance(n, dict) else n.__dict__ for n in nodes]
        req = ChainRequest(
            session_id=self._c._session_id,
            nodes=raw_nodes,
            entry_node=entry_node,
            initial_input=initial_input or {},
            correlation_id=correlation_id or uuid.uuid4().hex[:8],
            streaming=streaming,
            timeout=timeout,
        )
        self._c._chain_events[req.id] = []
        resp = self._c._rpc(req, timeout=timeout + 5, event_callback=on_event)

        if isinstance(resp, A2EError):
            return ChainResult(success=False, chain_id="",
                               final_output=None,
                               error={"code": resp.code, "message": resp.message},
                               events=self._c._chain_events.pop(req.id, []))

        if not isinstance(resp, ChainResponse):
            raise ConnectionError(f"Unexpected chain response: {type(resp)}")

        return ChainResult(
            success=resp.success,
            chain_id=resp.chain_id,
            final_output=resp.final_output,
            outputs=resp.outputs,
            duration_ms=resp.duration_ms,
            nodes_run=resp.nodes_run,
            error=resp.error,
            events=self._c._chain_events.pop(req.id, []),
        )
