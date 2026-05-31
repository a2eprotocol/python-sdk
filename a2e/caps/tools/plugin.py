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
            response = ToolCallResponse(
                req_id=req_id,
                data=result,
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
        # TOOL LIST
        # -------------------------------------------------------------
        if isinstance(msg, ToolListRequest):
            try:
                definitions = self._list_tools()
                response = ToolListResponse(
                    req_id=msg.id,
                    tools=[definition.model_dump() for definition in definitions]
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
