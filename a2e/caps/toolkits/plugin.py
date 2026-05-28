# ---------------------------------------------------------------------------
# BASE TOOLKIT PLUGIN (ABSTRACT)
# ---------------------------------------------------------------------------
import time
from abc import abstractmethod
from typing import Optional, Type, Dict
from pydantic import BaseModel
from a2e.caps.toolkits.protocol import (
    ToolkitListRequest,
    ToolkitConfigureRequest,
    TOOLKIT_TYPE_MAP
)
from a2e.caps.base import (
    A2EMessage,
    A2EError,
    A2EErrorCode
)
from a2e.core.plugins import (
    A2EPlugin
)


class ToolkitPlugin(A2EPlugin):
    """
    Abstract base for toolkit plugins.

    Handles:
    - Protocol routing
    - Push callbacks

    Delegates:
    - toolkit configuration
    - tool listing
    - tool execution
    """

    name = "toolkit_plugin"

    def __init__(self, host_instance, config):
        super().setup(host_instance, config)
        self._push_cb = None

    # -----------------------------------------------------------------------
    # PUSH SUPPORT
    # -----------------------------------------------------------------------
    def set_push_callback(self, fn):
        self._push_cb = fn

    def emit_event(self, event):
        if self._push_cb:
            try:
                self._push_cb(event)
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # ABSTRACT CONTRACT
    # -----------------------------------------------------------------------
    @abstractmethod
    def _configure_toolkit(self, msg):
        return NotImplementedError

    @abstractmethod
    def _list_toolkits(self, msg):
        return NotImplementedError

    # -----------------------------------------------------------------------
    # PROTOCOL HANDLER
    # -----------------------------------------------------------------------
    def supported_messages(self) -> Dict[str, Type[BaseModel]]:
        return TOOLKIT_TYPE_MAP

    def handle(self, msg: A2EMessage) -> Optional[A2EMessage]:
        response = None
        req_id = msg.id
        t0 = time.monotonic()

        # toolkit/list
        if isinstance(msg, ToolkitListRequest):
            try:
                response = self._list_toolkits(msg)
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

        if isinstance(msg, ToolkitConfigureRequest):
            try:
                return self._configure_toolkit(msg)
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

        # Return invalid message
        response = A2EError(**{
            "req_id": req_id,
            "code": A2EErrorCode.INVALID_MESSAGE,
            "message": f"Invalid message: {msg.type}",
            "retryable": False
        })
        self.audit_handle(msg, response, req_id, t0)
        return response
