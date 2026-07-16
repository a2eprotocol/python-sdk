# ---------------------------------------------------------------------------
# BASE TOOL PLUGIN
# ---------------------------------------------------------------------------
import pdb
import time
from pydantic import BaseModel
from typing import Any, Dict, Callable, Optional, Type, List

from a2e.caps.tools.protocol import (
    ToolCallRequest,
    ToolCallResponse,
    ToolResult,
    ToolEvent,
    ToolListRequest,
    ToolListResponse,
    ToolDefinition,
    ToolErrorCode,
    MessageType
)
from a2e.caps.base import (
    A2EMessage,
    A2EError,
    A2EErrorCode
)
from a2e.core.plugins import (
    A2EPlugin
)


class ToolPlugin(A2EPlugin):
    """
    Base class for all A2E native tools.

    Tools are:
      • Stateless
      • Request/response based
      • Optionally streaming
    """

    name: str = "base_tool"

    def __init__(self, host_instance, config: Any):
        super().setup(host_instance, config)
        self._event_cb: Optional[Callable[[ToolEvent], None]] = None

    # ---------------------------------------------------------------------
    # REQUIRED: Tool List
    # ---------------------------------------------------------------------
    def _list_tools(self) -> List[ToolDefinition]:
        """
        Must return tool manifest.
        """
        raise NotImplementedError

    # ---------------------------------------------------------------------
    # OPTIONAL: TOOL SEARCH (on-demand discovery)
    # ---------------------------------------------------------------------
    def _search_tools(
        self,
        query: str,
        filter_tags: list[str] | None = None,
        tools: list[ToolDefinition] | None = None,
    ) -> List[ToolDefinition]:
        """
        Default search: case-insensitive substring match against name/description.

        Override to plug in BM25, embeddings, or custom search strategies.
        Subclasses that call super() and extend the result list are also
        supported — the base impl covers static tool definitions.

        `tools` — optional pre-fetched tool list. When None, calls
        ``_list_tools()`` to get the full set.
        """
        query_lower = query.lower()
        filter_tags = filter_tags or []
        results: list[ToolDefinition] = []
        source = self._list_tools() if tools is None else tools

        for tool in source:
            # Tag pre-filter (AND semantics — tool must have ALL filter tags)
            if filter_tags:
                tool_tags_lower = {t.lower() for t in tool.tags}
                if not all(t.lower() in tool_tags_lower for t in filter_tags):
                    continue

            # Query match: name or description contains the query string
            if query_lower in tool.name.lower() or query_lower in tool.description.lower():
                results.append(tool)
                continue

            # Tag match: any tag contains the query string
            if any(query_lower in t.lower() for t in tool.tags):
                results.append(tool)
                continue

        return results

    # ---------------------------------------------------------------------
    # REQUIRED: EXECUTION
    # ---------------------------------------------------------------------
    def _execute_tool(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute tool logic.

        Should return JSON-serializable dict.
        Raise exception for failure.
        """
        raise NotImplementedError

    # ---------------------------------------------------------------------
    # OPTIONAL: STREAMING SUPPORT
    # ---------------------------------------------------------------------
    def set_event_callback(self, fn: Callable[[ToolEvent], None]):
        self._event_cb = fn

    def emit(self, kind: str, data: Dict[str, Any]):
        """
        Emit streaming event during execution.
        """
        if not self._event_cb:
            return

        try:
            evt = ToolEvent(
                kind=kind,
                data=data,
                seq=int(time.time() * 1000)
            )
            self._event_cb(evt)
        except Exception:
            pass

    # ---------------------------------------------------------------------
    # CORE EXECUTION WRAPPER
    # ---------------------------------------------------------------------
    def _execute(self, msg: ToolCallRequest) -> ToolCallResponse:
        """
        Safe execution wrapper:
          • handles errors
          • emits streaming events
          • enforces timeout (optional later)
        """
        response = None
        req_id = msg.id
        t0 = time.monotonic()
        try:
            result = self._execute_tool(msg.tool_name, msg.arguments or {})
            # The host plugin returns a plain JSON-serializable dict (per the
            # _execute_tool contract), but ToolCallResponse.data is typed as a
            # ToolResult. Coerce the raw payload into a ToolResult so the
            # response validates — otherwise pydantic raises a ValidationError
            # at construction time (outside this try/except) and the agent
            # receives a null/empty response. See bug: terminal tool returned
            # null consistently.
            if isinstance(result, ToolResult):
                tool_result = result
            else:
                payload = result if isinstance(result, dict) else {"value": result}
                tool_result = ToolResult(
                    success=True,
                    tool_name=msg.tool_name,
                    data=payload,
                    exit_code=payload.get("exit_code")
                    if isinstance(payload, dict)
                    else None,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
            response = ToolCallResponse(
                req_id=req_id,
                data=tool_result,
                created_at=time.time(),
            )
        except Exception as e:
            response = A2EError(
                req_id=req_id,
                code=ToolErrorCode.TOOL_ERROR,
                message=str(e),
                retryable=False,
            )
        finally:
            self.audit_handle(msg, response, req_id, t0)
            return response

    # ---------------------------------------------------------------------
    # PROTOCOL HANDLER
    # ---------------------------------------------------------------------
    def supported_messages(self) -> Dict[str, Type[BaseModel]]:
        return {
            MessageType.TOOL_LIST_REQ: ToolListRequest,
            MessageType.TOOL_CALL_REQ: ToolCallRequest,
        }

    def handle(self, msg: A2EMessage) -> Optional[A2EMessage]:
        """
        Handles tool/* messages.

        Returns response or None if not handled.
        """
        response = None
        req_id = msg.id
        t0 = time.monotonic()

        # -------------------------------------------------------------
        # TOOL LIST + SEARCH  — unified
        #   query="" (default): return non-deferred tools only
        #   query="..."      : search name/desc/tags, respect include_deferred
        # -------------------------------------------------------------
        if isinstance(msg, ToolListRequest):
            try:
                definitions = self._list_tools()

                # Search mode: filter by query string
                if msg.query:
                    definitions = self._search_tools(
                        msg.query,
                        filter_tags=msg.filter_tags or None,
                        tools=definitions,  # pass full list as source
                    )
                else:
                    # List mode: exclude deferred by default
                    if not msg.include_deferred:
                        definitions = [
                            d for d in definitions
                            if not d.defer_loading
                        ]

                response = ToolListResponse(
                    req_id=msg.id,
                    tools=[d.model_dump() for d in definitions],
                )
            except Exception as error:
                response = A2EError(**{
                    "req_id": req_id,
                    "code": A2EErrorCode.RUNTIME_ERROR,
                    "message": str(error),
                    "retryable": False
                })
            finally:
                self.audit_handle(msg, response, req_id, t0)
                return response

        # -------------------------------------------------------------
        # TOOL CALL
        # -------------------------------------------------------------
        if isinstance(msg, ToolCallRequest):
            # attach streaming callback — decorates events with req_id
            # then emits through the executor's standard path
            def _emit(evt: ToolEvent):
                evt.req_id = msg.id
                self.emit_event(evt)

            self.set_event_callback(_emit)

            return self._execute(msg)

        return None
