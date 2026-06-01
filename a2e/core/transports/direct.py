import pdb
import threading
import queue
from typing import Callable, Optional, Any
from a2e.core.transports.base import (
    BaseTransport
)


MessageHandler = Callable[[str], None]


class DirectTransport(BaseTransport):
    """
    In-memory transport using queues (no subprocess).

    Useful for:
    - local testing
    - embedded agent + host execution
    - RL environments (fast step loops)
    """

    def __init__(
        self,
        logger: Any,
    ):
        """
        in_queue  = messages coming INTO this side
        out_queue = messages sent FROM this side
        """
        super().__init__()
        self._in_queue: Optional[queue.Queue[str]] = queue.Queue(maxsize=1000)
        self._out_queue: Optional[queue.Queue[str]] = queue.Queue(maxsize=1000)
        self._logger = logger

        self._reader_thread: Optional[threading.Thread] = None
        self._alive = False

    def connect(self, other: "DirectTransport"):
        """
        Wire two transports together (bidirectional).
        """
        self._out_queue = other._in_queue
        other._out_queue = self._in_queue

    # ─────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────
    def start(self):
        if self._alive:
            raise RuntimeError("Transport already started")

        self._alive = True

        self._reader_thread = threading.Thread(
            target=self._read_loop,
            daemon=True,
        )
        self._reader_thread.start()

        self._logger.info("[direct-transport] started")

    def stop(self):
        if not self._alive:
            return

        self._alive = False

        try:
            self._in_queue.put_nowait(None)  # type: ignore
        except Exception as error:
            pass

        if self._reader_thread:
            self._reader_thread.join(timeout=1)

        self._logger.info("[direct-transport] stopped")

    def alive(self) -> bool:
        return self._alive

    # ─────────────────────────────────────────────
    # Messaging
    # ─────────────────────────────────────────────
    def set_message_handler(self, handler: MessageHandler):
        self._handler = handler

    async def deliver(self, msg: str):
        self._in_queue.put(msg)

    def send(
        self,
        msg: str,
        block: bool = True,
        timeout: float = 5.0,
    ):
        """
        Send message to the other side.

        Priority:
          1. _out_handler (explicit external handler — client mode)
          2. _out_queue   (wired via connect() — server direct mode)

        block=False → drop on overflow (low latency mode)
        """
        if not self._alive:
            raise RuntimeError("Transport not alive")

        if self._out_handler is not None:
            try:
                self._out_handler(msg)
                return
            except Exception as error:
                self._logger.warning(
                    "[direct-transport] out_handler error — %s", error
                )
                return

        # Fall back to wired queue (connect() sets this up)
        try:
            self._out_queue.put(msg, block=block, timeout=timeout)
        except queue.Full:
            self._logger.warning(
                "[direct-transport] send queue full — dropping message"
            )

    # ─────────────────────────────────────────────
    # Internal loop
    # ─────────────────────────────────────────────
    def _read_loop(self):
        while self._alive:
            try:
                msg = self._in_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if msg is None:
                continue

            if self._handler:
                try:
                    self._handler(msg)
                except Exception:
                    self._logger.exception(
                        "[direct-transport] handler error"
                    )
