"""
server.py — A2E Service Host

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
import os

import pdb
import threading
import time

from typing import Any
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse

from a2e.core.server.session_manager import (
    SessionManager
)
from a2e.core.server.executor import (
    A2EServerRuntimeExecutor
)
from a2e.schema import (
    A2EHostConfig
)



# ── A2E WIRE TRACE (env side) ────────────────────────────────────────────
# The env sandbox is where every A2E message actually LANDS, but its stdout
# used to carry uvicorn access lines only ("POST /send 200") — no message
# type, no ids, nothing that lets an operator say WHICH exchange failed. The
# agent side already logs its own send/receive; this is the symmetric trace on
# the environment side, at the ONE choke point every message crosses (the HTTP
# /send handler and the /stream response stream).
#
# Bounded by construction: the digest keeps the message TYPE, its id and a
# short slice of the interesting fields, never the whole payload. Disable with
# A2E_WIRE_TRACE=0.
_WIRE_FIELDS = ("step", "episode_id", "action", "observation", "reward",
                "done", "error", "tool", "command", "status", "success")
_WIRE_DIGEST_CHARS = 160


def _wire_trace_enabled() -> bool:
    return str(os.environ.get("A2E_WIRE_TRACE", "1")).strip() not in (
        "0", "false", "False", "")


def _trace_wire(logger, direction: str, raw, session_id: str = "") -> None:
    """Log one A2E message, both directions, bounded. Never raises."""
    try:
        if not _wire_trace_enabled():
            return
        import json as _json
        text = raw.decode("utf-8", "replace") if isinstance(
            raw, (bytes, bytearray)) else str(raw)
        mtype, mid, parts = "?", "", []
        try:
            data = _json.loads(text)
            if isinstance(data, dict):
                mtype = str(data.get("type") or "?")
                mid = str(data.get("id") or "")[:12]
                for key in _WIRE_FIELDS:
                    if key in data and data[key] not in (None, "", [], {}):
                        value = str(data[key]).replace("\n", " ")
                        parts.append("%s=%s" % (
                            key, value[:_WIRE_DIGEST_CHARS]))
        except Exception:  # noqa: BLE001 — not JSON: log the head only
            parts.append("raw=" + text[:_WIRE_DIGEST_CHARS])
        logger.info("[a2e-wire] %-3s type=%s id=%s session=%s bytes=%d %s",
                    direction, mtype, mid or "-", session_id or "-",
                    len(text), " ".join(parts))
    except Exception:  # noqa: BLE001 — tracing must never break the protocol
        pass

class A2EServer:
    """
    Transport-agnostic A2E Host.

    Works with:
    - HTTPTransport
    - DirectTransport

    Core flow:
        transport → handle_raw → decode → dispatch → send
    """
    def __init__(
        self,
        config: A2EHostConfig,
        logger: Any,
        max_workers: int = 16,
    ):
        self._config = config
        self._transports = []
        self._runtimes = []

        self._mode = self._config.transport.type

        self.sessions = SessionManager(config, logger)
        self.logger = logger

        self._alive = False
        self._start_ts = time.monotonic()
        self._session_id = None

        self._lock = threading.Lock()

        # execution control
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def start(self):
        if self._mode == "direct":
            self._start_direct()
        elif self._mode == "http":
            return self._start_http()
        else:
            raise ValueError(f"Unsupported transport: {self._mode}")

    def _start_direct(self):
        from a2e.core.transports.direct import DirectTransport

        t1 = DirectTransport(logger=self.logger)
        t2 = DirectTransport(logger=self.logger)
        t1.connect(t2)
        r1 = A2EServerRuntimeExecutor(self._config, t1, self.logger)
        r2 = A2EServerRuntimeExecutor(self._config, t2, self.logger)
        r1.start()
        r2.start()
        self._transports.extend([t1, t2])
        self._runtimes.extend([r1, r2])
        self.logger.info("[a2e] direct mode started")
        return r1, r2

    def _start_http(self) -> FastAPI:
        app = FastAPI()

        @app.post("/session")
        def create_session():
            s = self.sessions.create()
            return {"session_id": s.id}

        @app.post("/send")
        async def send(request: Request):
            sid = request.headers.get("X-Session-Id")
            if not sid:
                raise HTTPException(400, "Missing X-Session-Id")

            try:
                session = self.sessions.get(sid)
            except KeyError:
                raise HTTPException(404, "Session not found")

            body = await request.body()
            msg = body.decode()
            _trace_wire(self.logger, "in", msg, sid)
            await session.transport.deliver(msg)
            return {"ok": True}

        @app.get("/stream")
        async def stream(request: Request):
            sid = request.headers.get("X-Session-Id")
            if not sid:
                raise HTTPException(400, "Missing X-Session-Id")

            try:
                session = self.sessions.get(sid)
            except KeyError:
                raise HTTPException(404, "Session not found")

            async def event_stream():
                async for msg in session.stream():
                    if await request.is_disconnected():
                        self.logger.info(f"[session] disconnected {sid}")
                        return

                    _trace_wire(self.logger, "out", msg, sid)
                    yield f"data: {msg}\n\n"

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={
                   "Cache-Control": "no-cache",
                   "Connection": "keep-alive",
                },
            )

        @app.get("/health")
        def health():
            return {"status": "ok"}

        return app

    def stop(self):
        for r in self._runtimes:
            try:
                r.stop()
            except Exception:
                self.logger.exception("runtime stop failed")
