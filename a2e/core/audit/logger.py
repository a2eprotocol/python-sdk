import json
import threading
from pathlib import Path
from typing import Any

from a2e.core.audit.schema import AuditEntry


class AuditLog:
    def __init__(
        self,
        path: Path,
        logger: Any
    ):
        self._path = path
        self.logger = logger
        self._lock = threading.Lock()

    def record(self, entry: AuditEntry):
        line = json.dumps(entry.model_dump(), separators=(",", ":"))
        self.logger.info(f"[audit] {line}")
        if self._path:
            with self._lock:
                with self._path.open("a") as f:
                    f.write(line + "\n")
