"""
subprocess.py — SubprocessTransport

Launches a child process and communicates with it over stdin/stdout
using line-delimited NDJSON. Each message is a single JSON line.

Useful for:
- running an agent as a subprocess
- connecting to A2E-compatible CLIs
- testing with real process boundaries
"""
from __future__ import annotations

import os
import sys
import json
import queue
import signal
import threading
import subprocess as sp
from typing import Callable, Optional, Any

from a2e.core.transports.base import BaseTransport


MessageHandler = Callable[[str], None]


class SubprocessTransport(BaseTransport):
    """
    Spawns a subprocess and communicates line-delimited JSON over
    its stdin/stdout streams.
    """

    def __init__(
        self,
        command: list[str],
        logger: Any,
        *,
        env: Optional[dict[str, str]] = None,
        cwd: Optional[str] = None,
        max_queue_size: int = 1000,
        start_timeout: float = 5.0,
    ):
        super().__init__()
        self._cmd = command
        self._logger = logger
        self._env = env
        self._cwd = cwd
        self._max_queue_size = max_queue_size
        self._start_timeout = start_timeout

        self._proc: Optional[sp.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._alive = False
        self._stop_evt = threading.Event()
        self._write_lock = threading.Lock()

    # ─────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────
    def start(self):
        if self._alive:
            raise RuntimeError("Transport already started")

        self._stop_evt.clear()

        self._proc = sp.Popen(
            self._cmd,
            stdin=sp.PIPE,
            stdout=sp.PIPE,
            stderr=sp.PIPE,
            env={**os.environ, **(self._env or {})},
            cwd=self._cwd,
            bufsize=0,  # unbuffered
        )

        self._alive = True

        self._reader_thread = threading.Thread(
            target=self._read_loop,
            daemon=True,
        )
        self._reader_thread.start()

        self._logger.info(
            "[subprocess-transport] started pid=%d cmd=%s",
            self._proc.pid,
            " ".join(self._cmd),
        )

    def stop(self):
        if not self._alive:
            return

        self._stop_evt.set()
        self._alive = False

        if self._proc:
            # Close stdin so the subprocess gets EOF on its read
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
            except OSError:
                pass

            # Wait briefly for graceful shutdown
            try:
                self._proc.wait(timeout=3)
            except sp.TimeoutExpired:
                self._logger.warning(
                    "[subprocess-transport] process did not exit in time, sending SIGTERM"
                )
                try:
                    self._proc.terminate()
                    self._proc.wait(timeout=2)
                except sp.TimeoutExpired:
                    self._logger.warning(
                        "[subprocess-transport] process still alive, sending SIGKILL"
                    )
                    self._proc.kill()
                    self._proc.wait(timeout=2)
            except Exception:
                pass

        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2)

        self._logger.info("[subprocess-transport] stopped pid=%d", self._proc.pid if self._proc else -1)

    def alive(self) -> bool:
        return self._alive and self._proc is not None and self._proc.poll() is None

    # ─────────────────────────────────────────────
    # Messaging
    # ─────────────────────────────────────────────

    def set_message_handler(self, handler: MessageHandler):
        self._handler = handler

    async def deliver(self, msg: str):
        """Deliver a message incoming from the other side (server-side)."""
        if self._handler:
            self._handler(msg)

    def send(self, msg: str):
        """Write a single NDJSON line to the subprocess stdin."""
        if not self._alive or not self._proc or not self._proc.stdin:
            raise RuntimeError("Transport not started or not alive")

        with self._write_lock:
            try:
                self._proc.stdin.write((msg + "\n").encode("utf-8"))
                self._proc.stdin.flush()
            except BrokenPipeError:
                self._alive = False
                raise RuntimeError("Subprocess stdin closed (process exited)")

    # ─────────────────────────────────────────────
    # Internal: stdout reader
    # ─────────────────────────────────────────────

    def _read_loop(self):
        """Read line-delimited JSON from the subprocess stdout."""
        while not self._stop_evt.is_set():
            try:
                if not self._proc or not self._proc.stdout:
                    break

                line = self._proc.stdout.readline()
                if not line:
                    # EOF — subprocess closed stdout
                    if not self._stop_evt.is_set():
                        self._logger.warning(
                            "[subprocess-transport] stdout EOF"
                        )
                    break

                raw = line.decode("utf-8").rstrip("\r\n")
                if not raw:
                    continue

                if self._handler:
                    try:
                        self._handler(raw)
                    except Exception:
                        self._logger.exception(
                            "[subprocess-transport] handler error"
                        )

            except Exception as exc:
                if self._stop_evt.is_set():
                    break
                self._logger.warning(
                    "[subprocess-transport] read error: %s",
                    exc,
                )
                break

        self._alive = False
