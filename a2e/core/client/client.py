"""
client.py — A2E Agent-side base client class

The client wraps the A2E protocol from the agent's perspective:
  - opens a connection to the host (subprocess or socket)
  - handles the handshake
  - surfaces streaming events progressively to a callback
"""
from __future__ import annotations

import pdb
import json
import time
import uuid
import queue
from typing import Any, Callable, Dict, Optional

from a2e.caps.base.protocol import (
    A2EMessage,
    A2EError,
    Capability,
    HandshakeRequest,
    HandshakeResponse,
    Ping,
    Shutdown,
    A2EEvent,
    A2E_BASE_TYPE_MAP
)

EventCallback = Callable[[A2EEvent], None]


class A2EClientError(Exception):
    def __init__(self, err: A2EError, events=None):
        super().__init__(f"[{err.code}] {err.message}")

        self.code = err.code
        self.message = err.message
        self.retryable = err.retryable
        self.detail = err.detail or {}
        self.capability_name = err.capability_name
        self.req_id = err.req_id
        self.events = events or []


class A2EClient:
    """
    Transport-agnostic A2E client.

    Supports:
    - HTTPTransport
    """

    def __init__(
        self,
        transport: Any,
        logger: Any,
        agent_id: str = "",
        auth_token: str = "",
        agent_caps: Optional[list[str]] = None,
        type_registry: Optional[Dict[str, type]] = None,
    ):
        self._transport = transport
        self.logger = logger

        self._agent_id = agent_id or uuid.uuid4().hex[:8]
        self._auth_token = auth_token
        self._agent_caps = agent_caps or ["streaming", "artifacts"]

        self._session_id: str = ""
        self._accepted_caps: list[Capability] = []

        self._pending: Dict[str, queue.Queue] = {}
        self._events: Dict[str, list[A2EEvent]] = {}

        # Push message handlers: msg_type → list of callbacks
        # For unsolicited server-initiated messages (no pending RPC).
        self._push_handlers: Dict[str, list[Callable]] = {}

        self._type_registry = type_registry or {}
        self._type_registry.update(A2E_BASE_TYPE_MAP)
        self._alive = False

    def update_msg_types(self, msg_types):
        self._type_registry.update(msg_types)

    def register_push_handler(self, msg_type: str, callback: Callable):
        """
        Register a callback for unsolicited push messages of a given type.
        These are server-initiated messages that arrive without a matching
        pending RPC (e.g. EnvStatePush, MCPServerPush, ProcReadEvent).
        """
        self._push_handlers.setdefault(msg_type, []).append(callback)

    def unregister_push_handler(self, msg_type: str, callback: Callable):
        """Remove a previously registered push handler."""
        handlers = self._push_handlers.get(msg_type, [])
        try:
            handlers.remove(callback)
        except ValueError:
            pass

    # ─────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────
    def connect(self):
        """Start transport + handshake"""
        if not hasattr(self._transport, "set_message_handler"):
            raise RuntimeError("Transport must support set_message_handler")

        if hasattr(self._transport, "set_message_handler"):
            self._transport.set_message_handler(self._on_message)

        self._transport.start()
        self._alive = True

        self._handshake()

    def disconnect(self):
        if not self._alive:
            return

        if self._session_id:
            try:
                self._send(Shutdown())
            except Exception:
                pass

        self._alive = False

        try:
            self._transport.stop()
        except Exception:
            self.logger.exception("[client] transport stop failed")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()

    # ─────────────────────────────────────────────
    # Core Messaging
    # ─────────────────────────────────────────────
    def _send(self, msg: A2EMessage):
        if not self._alive:
            raise RuntimeError("Client not connected")

        try:
            line = self.encode(msg)
            self._transport.send(line)
        except Exception as e:
            self.logger.exception("[client] send failed")

    def _on_message(self, raw: str):
        """Transport callback → route messages"""
        if not raw:
            return

        try:
            msg = self.decode(raw)
        except ValueError as e:
            self.logger.warning(f"[client] bad message: {e}")
            return

        req_id = getattr(msg, "req_id", None)

        # ── Pending RPC match ─────────────────
        if req_id and req_id in self._pending:
            self._pending[req_id].put(msg)
            return

        # ── Event tied to an active RPC ─────────
        if req_id and req_id in self._events:
            for h in self._events.get(req_id, []):
                h(msg)
            return

        # ── Unsolicited push message ──────────
        msg_type = str(getattr(msg, "type", "") or "")
        if msg_type and msg_type in self._push_handlers:
            for h in self._push_handlers[msg_type]:
                h(msg)
            return

    # ─────────────────────────────────────────────
    # RPC
    # ─────────────────────────────────────────────
    def rpc(
        self,
        req: A2EMessage,
        timeout: float = 300.0,
        event_callback: EventCallback = None,
    ) -> A2EMessage:

        q: queue.Queue = queue.Queue()
        self._pending[req.id] = q

        self._send(req)

        deadline = time.monotonic() + timeout

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                del self._pending[req.id]
                raise TimeoutError(f"RPC timeout for {req.id}")

            try:
                msg = q.get(timeout=min(remaining, 1.0))
            except queue.Empty:
                continue

            if isinstance(msg, A2EEvent):
                self._events.setdefault(req.id, []).append(msg)
                if event_callback:
                    event_callback(msg)

            # ─────────────────────────────
            # 🔥 A2E Error
            # ─────────────────────────────
            if isinstance(msg, A2EError):
                events = self._events.get(req.id, [])
                self._pending.pop(req.id, None)
                self._events.pop(req.id, None)
                raise A2EClientError(msg, events=events)

            del self._pending[req.id]
            return msg

    # ─────────────────────────────────────────────
    # Handshake
    # ─────────────────────────────────────────────
    def _handshake(self):
        req = HandshakeRequest(
            agent_id=self._agent_id,
            agent_caps=self._agent_caps,
            auth_token=self._auth_token,
        )

        resp = self.rpc(req, timeout=30)
        if not isinstance(resp, HandshakeResponse) or not resp.ok:
            reason = (
                resp.reason
                if isinstance(resp, HandshakeResponse)
                else str(resp)
            )
            raise ConnectionError(f"Handshake failed: {reason}")

        self._session_id = resp.session_id

        # negotiated capabilities
        self._accepted_caps = resp.accepted_caps

        # convenience lookup map
        self._capability_map = {
            cap.capability: cap
            for cap in resp.accepted_caps
            if cap.enabled
        }

        self.logger.info(
            "[client] handshake ok "
            f"session={self._session_id} "
            f"capabilities={[c.capability for c in resp.accepted_caps]}"
        )

        self.logger.debug(
            "[client] negotiated capabilities=%s",
            [
                {
                    "capability": cap.capability,
                    "metadata": cap.metadata,
                }
                for cap in resp.accepted_caps
            ],
        )

    def capabilities(self) -> List[Capability]:
        return self._accepted_caps

    # ─────────────────────────────────────────────
    # Utilities
    # ─────────────────────────────────────────────
    def ping(self, timeout: float = 5.0) -> float:
        t0 = time.monotonic()
        _ = self.rpc(Ping(), timeout=timeout)
        return (time.monotonic() - t0) * 1000

    def encode(self, msg: A2EMessage) -> str:
        return json.dumps(msg.to_dict(), separators=(",", ":"), default=str)

    def decode(self, line: str) -> A2EMessage:
        try:
            data = json.loads(line)
        except Exception as e:
            raise ValueError(f"Invalid JSON: {e}")

        msg_type = data.get("type")
        if not msg_type:
            raise ValueError("Missing 'type' field")

        cls = self._type_registry.get(msg_type)

        # 🔥 Fallback: unknown message → generic wrapper
        if not cls:
            self.logger.debug(f"[client] Unknown message type: {msg_type}")
            return A2EMessage.model_validate(data)

        try:
            return cls.model_validate(data)
        except Exception as e:
            raise ValueError(f"Validation failed for {msg_type}: {e}")
