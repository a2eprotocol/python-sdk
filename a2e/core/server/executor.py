"""
executor.py — A2E per Session Executor

The server is the server-side of the Base A2E Communication Protocol.
It sits between the agent and the environment, and is responsible for:

  1. Answering handshake requests
  2. Validating invoke requests against the JSON Schema
  4. Routing invocations to the respective service/plugin
  5. Streaming InvokeEvent messages back to the agent
  6. Enforcing resource limits declared in the manifest
  7. Emitting a structured audit log entry per invocation

Transport: line-delimited JSON over stdin/stdout (or any stream pair).
"""

from __future__ import annotations

import pdb
import uuid
import json
import threading
import time
import importlib
from pydantic import BaseModel, ValidationError
from typing import Any, Dict, List, Type, Optional
from concurrent.futures import ThreadPoolExecutor
from a2e.core.audit import (
    build_session_id,
    build_audit_log
)
from a2e.caps.base.protocol import (
    A2EErrorCode,
    A2EError,
    A2EMessage,
    HandshakeRequest,
    HandshakeResponse,
    Ping,
    Pong,
    Shutdown,
    Capability,
    A2E_BASE_TYPE_MAP
)
from a2e.core.plugins import (
    A2EPlugin
)
from a2e.schema import (
    A2EHostConfig
)


class A2EServerRuntimeExecutor:
    """
    Transport-agnostic A2E Runtime.

    Works with:
    - DirectTransport

    Core flow:
        transport → handle_raw → decode → dispatch → send
    """

    def __init__(
        self,
        config: A2EHostConfig,
        transport: Any,
        logger: Any,
        max_workers: int = 16,
    ):
        self._config = config
        self.transport = transport
        self.logger = logger

        self._alive = False
        self._start_ts = time.monotonic()
        self._session_id = None

        self._lock = threading.Lock()

        # execution control
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

        # plugin system
        self.plugins: Dict[str, A2EPlugin] = {}
        self.type_registry: Dict[str, Type[BaseModel]] = {}
        self.type_to_plugins: Dict[str, List[A2EPlugin]] = {}
        self.type_registry.update(A2E_BASE_TYPE_MAP)

    # ─────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────
    def start(self):
        self._alive = True

        # Load plugins
        self._load_plugins()
        self._build_registry()

        # bind transport → runtime
        if hasattr(self.transport, "set_message_handler"):
            self.transport.set_message_handler(self.handle_raw)
        else:
            raise RuntimeError("Transport must support set_message_handler")

        # start runtime
        self.transport.start()

        self.logger.info("[a2e-server] started")

    def stop(self):
        self._alive = False

        self.logger.info("[a2e-server] stopping...")

        # stop transport first (stop incoming traffic)
        try:
            self.transport.stop()
        except Exception:
            self.logger.exception("transport stop failed")

        # shutdown executor (finish in-flight work)
        self._executor.shutdown(wait=True)

        # teardown plugins
        for p in self.plugins.values():
            try:
                p.teardown()
            except Exception:
                self.logger.exception("plugin teardown failed")

        self.logger.info("[a2e-server] stopped")

    # ─────────────────────────────────────────────
    # Plugin System
    # ─────────────────────────────────────────────
    def _load_plugins(self):
        audit      = build_audit_log(self._config)
        session_id = build_session_id(self._config)

        for pconf in self._config.plugins:
            if not pconf.metadata.enabled:
                continue

            plugin_config = {
                **(pconf.metadata.model_dump() or {}),
                "type": pconf.type,
                "audit_log":  audit,
                "session_id": session_id,
            }

            plugin = self._instantiate(pconf.cls, plugin_config)
            plugin.priority  = pconf.metadata.priority
            plugin.exclusive = pconf.metadata.exclusive
            self.plugins[pconf.name] = plugin

            # Wire push callback for plugins that support async events
            if hasattr(plugin, 'set_push_callback'):
                plugin.set_push_callback(self._send)

        self.logger.info(
            f"[a2e-server] Loaded {len(self.plugins)} plugins"
        )

    def _instantiate(self, cls_path: str, config: any):
        module_path, cls_name = cls_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, cls_name)
        return cls(self, config)

    # ── plugin resolution bridges (used by cross-capability plugins, e.g. chains) ──
    def get_plugin(self, name: str):
        """Return a loaded plugin by capability name (e.g. "tools", "proc")."""
        return self.plugins.get(name)

    def send(self, msg: BaseModel):
        """Public send used by plugins to emit push events (ChainEvent, …)."""
        self._send(msg)

    def _build_registry(self):
        self.type_to_plugins.clear()

        for plugin in self.plugins.values():
            for msg_type, model in plugin.supported_messages().items():
                self.type_registry[msg_type] = model
                self.type_to_plugins.setdefault(msg_type, []).append(plugin)

        for msg_type in self.type_to_plugins:
            self.type_to_plugins[msg_type].sort(
                key=lambda p: p.priority,
                reverse=True,
            )

    def _negotiate_caps(self, agent_caps: list[str]) -> list[Capability]:
        accepted_caps: list[Capability] = []
        for plugin_name, plugin in self.plugins.items():
            if plugin.config['type'] not in agent_caps:
                continue

            accepted_caps.append(
                Capability(
                    capability=plugin.config['type'],
                    metadata=plugin.caps_metadata(),
                )
            )

        return accepted_caps

    def _new_session_id(self):
        return uuid.uuid4().hex

    def _handle_core(self, msg: A2EMessage) -> bool:
        """
        Returns True if message was handled here.
        """

        # ─────────────────────────────
        # Handshake
        # ─────────────────────────────
        if isinstance(msg, HandshakeRequest):
            accepted = self._negotiate_caps(msg.agent_caps)

            resp = HandshakeResponse(
                req_id=msg.id,
                session_id=self._session_id or self._new_session_id(),
                accepted_caps=accepted,
                ok=True,
            )

            self._send(resp)
            return True

        # ─────────────────────────────
        # Ping
        # ─────────────────────────────
        if isinstance(msg, Ping):
            resp = Pong(
                req_id=msg.id,
                uptime_seconds=time.monotonic() - self._start_ts
            )
            self._send(resp)
            return True

        # ─────────────────────────────
        # Shutdown
        # ─────────────────────────────
        if isinstance(msg, Shutdown):
            self._alive = False
            return True

        return False

    def handle_raw(self, raw_line: str):
        if not self._alive:
            return

        raw_line = raw_line.strip()
        if not raw_line:
            return

        try:
            msg = self.decode(raw_line)
        except ValueError as e:
            req_id = ""
            try:
                data = json.loads(raw_line)
                req_id = data.get("id", "")
            except Exception:
                pass

            self._safe_send_error(
                req_id=req_id,
                code=A2EErrorCode.PARSE_ERROR,
                message=str(e),
            )
            return

        # control plane messages
        if self._handle_core(msg):
            return

        # dispatch async
        self._executor.submit(self._dispatch, msg)

    # ─────────────────────────────────────────────
    # Dispatch
    # ─────────────────────────────────────────────
    def _dispatch(self, message: BaseModel):
        msg_type = getattr(message, "type", None)
        req_id = getattr(message, "id", "")

        plugins = self.type_to_plugins.get(msg_type)

        if not plugins:
            self._safe_send_error(
                req_id,
                A2EErrorCode.UNKNOWN_TYPE,
                f"No handler for {msg_type}",
            )
            return

        try:
            if plugins[0].exclusive:
                self._run_plugin(plugins[0], message)
            else:
                for p in plugins:
                    self._run_plugin(p, message)

        except Exception as e:
            self.logger.exception("dispatch error")
            self._safe_send_error(
                req_id,
                A2EErrorCode.INTERNAL_ERROR,
                str(e),
            )

    def _run_plugin(self, plugin: A2EPlugin, message: BaseModel):
        res = plugin.handle(message)
        if res:
            # Auto-inject req_id from the incoming request so the client
            # can route the response to the correct pending RPC
            if hasattr(res, "req_id"):
                res.req_id = getattr(res, "req_id", "") or getattr(message, "id", "")
            self._send(res)

    # ─────────────────────────────────────────────
    # Send Helpers
    # ─────────────────────────────────────────────

    def _send(self, msg: BaseModel):
        if not self._alive:
            return

        try:
            line = self.encode(msg)
            print(f"line: {line}")
            self.transport.send(line)
        except Exception:
            self.logger.exception("send failed")

    def _safe_send_error(
        self,
        req_id: Optional[str],
        code: A2EErrorCode,
        message: str,
    ):
        err = A2EError(
            code=code.value,
            message=message,
            req_id=req_id or "",
            retryable=False
        )
        self._send(err)

    # ─────────────────────────────────────────────
    # Encoding / Decoding
    # ─────────────────────────────────────────────

    def encode(self, msg: A2EMessage) -> str:
        return json.dumps(
            msg.to_dict(),
            separators=(",", ":"),
            default=str,
        )

    def decode(self, line: str) -> BaseModel:
        data = json.loads(line)
        msg_type = data.get("type")

        cls = self.type_registry.get(msg_type)
        if not cls:
            raise ValueError(f"Unknown type {msg_type}")

        try:
            return cls.model_validate(data)
        except ValidationError as e:
            raise ValueError(str(e))
