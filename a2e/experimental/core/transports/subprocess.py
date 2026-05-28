import pdb
import subprocess
import threading
from typing import Iterator, Any


# ═════════════════════════════════════════════════════════════════════════════
# Transport (abstracts subprocess vs socket)
# ═════════════════════════════════════════════════════════════════════════════
class SubprocessTransport:
    """
    Starts the SCP host as a subprocess and communicates over stdin/stdout.
    The simplest transport — works with the host.py CLI entry point.
    """
    def __init__(
        self,
        cmd: list[str],
        logger: Any
    ):
        self._cmd = cmd
        self.logger = logger
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def start(self):
        self._proc = subprocess.Popen(
            self._cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,   # line-buffered
        )
        self.logger.info(f"[transport] Host process started (pid={self._proc.pid})")

    def stop(self):
        if self._proc:
            try:
                self._proc.stdin.close()
                self._proc.wait(timeout=10)
            except Exception:
                self._proc.kill()

    def write(self, line: str):
        with self._lock:
            self._proc.stdin.write(line + "\n")
            self._proc.stdin.flush()

    def lines(self) -> Iterator[str]:
        for line in self._proc.stdout:
            yield line.strip()

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None
