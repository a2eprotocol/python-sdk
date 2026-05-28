import queue
import threading
import time
import requests
from typing import Callable, Optional, Iterator, Any
from a2e.core.transports.base import (
    BaseTransport
)


MessageHandler = Callable[[str], None]


class HTTPTransport(BaseTransport):
    """
    HTTP + SSE transport for A2E.

    Model:
        send()  → POST /send
        receive → SSE stream (/stream)

    Supports:
        - event-driven mode (set_message_handler)
        - pull mode (lines()) for backward compatibility
    """

    _SENTINEL = object()

    def __init__(
        self,
        base_url: str,
        logger: Any,
        *,
        send_path: str = "/send",
        stream_path: str = "/stream",
        session_id: Optional[str] = None,
        session_factory: Optional[Callable[[requests.Session], str]] = None,
        connect_timeout: float = 5.0,
        read_timeout: float = 30.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        max_queue_size: int = 1000,
        drop_on_full: bool = True,
        headers: Optional[dict[str, str]] = None,
    ):
        """
        Args:
            base_url: Scheme + host + optional port, e.g. "http://localhost:8765".
            send_path: POST endpoint for outgoing SCP lines.
            stream_path: GET endpoint that returns an SSE stream of incoming lines.
            session_id: If set, sent as X-Session-Id on every request.
            connect_timeout: Seconds to wait for the TCP handshake on each request.
            read_timeout: Seconds to wait for a POST response body (stream reads
                             use no read timeout — the connection must stay open).
            max_retries: How many times to retry a failed write() before raising.
            retry_delay: Base delay between write retries (seconds).
            headers: Extra HTTP headers merged into every request.
        """
        super().__init__()

        self._base_url = str(base_url).rstrip("/")
        self.logger = logger
        self._send_url = f"{self._base_url}/{send_path.lstrip('/')}"
        self._stream_url = f"{self._base_url}/{stream_path.lstrip('/')}"

        self._session_id = session_id
        self._session_factory = session_factory

        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._max_retries = max_retries
        self._retry_delay = retry_delay

        self._extra_headers = headers or {}

        self._queue: queue.Queue[str | object] = queue.Queue(
            maxsize=max_queue_size
        )
        self._drop_on_full = drop_on_full

        self._http: Optional[requests.Session] = None
        self._reader: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._write_lock = threading.Lock()

        self._interceptor: Optional[Callable[[str], str]] = None

        self._alive_flag = False

    # ─────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────
    def start(self):
        if self._alive_flag:
            raise RuntimeError("Transport already started")

        self._http = requests.Session()

        # create or attach session
        if self._session_factory:
            self._session_id = self._session_factory(self._http)
        else:
            resp = self._http.post(f"{self._base_url}/session")
            resp.raise_for_status()
            self._session_id = resp.json()["session_id"]

        self._http.headers.update({
            "Content-Type": "text/plain",
            "Accept": "text/event-stream",
            "X-Session-Id": self._session_id,
            **self._extra_headers,
        })

        self._stop_evt.clear()
        self._alive_flag = True

        self._reader = threading.Thread(
            target=self._sse_reader,
            daemon=True,
        )
        self._reader.start()

        self.logger.info(f"[http-transport] started session={self._session_id}")

    def stop(self):
        if not self._alive_flag:
            return

        self._stop_evt.set()
        self._alive_flag = False

        try:
            self._queue.put_nowait(self._SENTINEL)
        except queue.Full:
            pass

        if self._reader and self._reader.is_alive():
            self._reader.join(timeout=5)
            self._reader = None

        if self._http:
            self._http.close()
            self._http = None

        self.logger.info("[http-transport] stopped")

    def alive(self) -> bool:
        return (
            self._alive_flag
            and self._reader is not None
            and self._reader.is_alive()
        )

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    # ─────────────────────────────────────────────
    # Messaging
    # ─────────────────────────────────────────────
    def set_message_handler(self, handler: MessageHandler):
        self._handler = handler

    def set_interceptor(self, fn: Callable[[str], str]):
        self._interceptor = fn

    def send(self, msg: str):
        if not self._alive_flag or not self._http:
            raise RuntimeError("Transport not started or not alive")

        if self._interceptor:
            msg = self._interceptor(msg)

        with self._write_lock:
            last_exc: Optional[Exception] = None

            for attempt in range(1, self._max_retries + 1):
                try:
                    resp = self._http.post(
                        self._send_url,
                        data=msg,
                        timeout=(self._connect_timeout, self._read_timeout),
                    )
                    resp.raise_for_status()
                    return

                except requests.RequestException as exc:
                    last_exc = exc

                    if attempt < self._max_retries:
                        self.logger.warning(
                            "[http-transport] send failed (%d/%d): %s → retrying",
                            attempt,
                            self._max_retries,
                            exc,
                        )
                        time.sleep(self._retry_delay)

            self._alive_flag = False
            raise RuntimeError("HTTP send failed") from last_exc

    def deliver(self, msg: str):
        self._dispatch(msg)

    # ─────────────────────────────────────────────
    # Pull mode (optional)
    # ─────────────────────────────────────────────
    def lines(self) -> Iterator[str]:
        while True:
            item = self._queue.get()

            if item is self._SENTINEL:
                self._queue.put(self._SENTINEL)
                return

            yield item

    # ─────────────────────────────────────────────
    # Internal: SSE Reader
    # ─────────────────────────────────────────────
    def _sse_reader(self):
        backoff = self._retry_delay

        while not self._stop_evt.is_set():
            try:
                with self._http.get(
                    self._stream_url,
                    stream=True,
                    timeout=(self._connect_timeout, None),
                    headers={"Accept": "text/event-stream"},
                ) as resp:

                    resp.raise_for_status()
                    self.logger.info("[http-transport] SSE connected")
                    backoff = self._retry_delay

                    for msg in self._parse_sse(resp):
                        if self._stop_evt.is_set():
                            return

                        self._dispatch(msg)

                    self.logger.warning("[http-transport] SSE closed")
            except Exception as exc:
                if self._stop_evt.is_set():
                    return

                self.logger.warning(
                    "[http-transport] SSE error: %s → retrying in %.1fs",
                    exc,
                    backoff,
                )

                self._stop_evt.wait(backoff)
                backoff = min(backoff * 2, 30.0)

        try:
            self._queue.put_nowait(self._SENTINEL)
        except queue.Full:
            pass

    def _dispatch(self, msg: str):
        if self._handler:
            try:
                self._handler(msg)
            except Exception:
                self.logger.exception("[http-transport] handler error")
            return

        try:
            self._queue.put(
                msg,
                block=not self._drop_on_full,
                timeout=0.1,
            )
        except queue.Full:
            self.logger.warning(
                "[http-transport] queue full — dropping message"
            )

    # ─────────────────────────────────────────────
    # SSE Parsing
    # ─────────────────────────────────────────────
    @staticmethod
    def _parse_sse(resp: requests.Response) -> Iterator[str]:
        pending: list[str] = []

        for raw in resp.iter_lines(decode_unicode=True):
            if raw is None:
                continue

            if raw == "":
                if pending:
                    yield "\n".join(pending)
                    pending.clear()
                continue

            if raw.startswith(":"):
                continue

            if ":" in raw:
                field, _, value = raw.partition(":")
                value = value.lstrip(" ")

                if field == "data":
                    pending.append(value)
            else:
                if raw == "data":
                    pending.append("")

        if pending:
            yield "\n".join(pending)
