import pdb
import uuid
from typing import List, Callable

from a2e.core.client import A2EClient
from a2e.caps.base.protocol import A2EError
from a2e.caps.tools import (
    ToolListRequest,
    ToolListResponse,
    ToolCallRequest,
    ToolCallResponse,
    ToolDefinition,
    ToolResult,
    ToolEvent,
    TOOL_TYPE_MAP
)


ToolEventCallback = Callable[[ToolEvent], None]


class ToolAPI:
    def __init__(self, client: A2EClient):
        self._c = client
        self._c.update_msg_types(TOOL_TYPE_MAP)

    def list(
        self,
        kind: str = "",
        tags: list[str] | None = None,
        timeout: int = 10,
    ) -> List[ToolDefinition]:
        req = ToolListRequest(
            filter_kind=kind,
            filter_tags=tags or []
        )
        resp = self._c.rpc(req, timeout=timeout)
        if not isinstance(resp, ToolListResponse):
            raise ConnectionError(
                f"Unexpected tool list response: {type(resp)}"
            )

        self._c._tools_cache = [
            ToolDefinition.model_validate(t)
            for t in resp.tools
        ]
        return self._c._tools_cache

    def call(
        self,
        tool_name: str,
        arguments: dict,
        *,
        streaming: bool = True,
        on_event: ToolEventCallback = None,
        timeout: int = 60,
        correlation_id: str = "",
    ) -> ToolResult:
        req = ToolCallRequest(
            session_id=self._c._session_id,
            tool_name=tool_name,
            arguments=arguments,
            streaming=streaming,
            timeout=timeout,
            correlation_id=correlation_id or uuid.uuid4().hex[:8],
        )
        resp = self._c.rpc(req, timeout=timeout + 5, event_callback=on_event)

        if isinstance(resp, A2EError):
            return ToolResult(
                success=False,
                tool_name=tool_name,
                data=None,
                duration_ms=0,
                error=resp.message,
                error_code=resp.code,
                events=[]  # self._c._tool_events.pop(req.id, [])
            )

        if not isinstance(resp, ToolCallResponse):
            raise ConnectionError(f"Unexpected tool response: {type(resp)}")

        return resp.data
