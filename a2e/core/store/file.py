import json
from pathlib import Path
from a2e.core.store.base import (
    SnapshotStore
)


class FileSnapshotStore(SnapshotStore):

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def save(self, key: str, state: dict):
        with open(self._path(key), "w") as f:
            json.dump(state, f)

    def load(self, key: str) -> dict:
        with open(self._path(key)) as f:
            return json.load(f)

    def delete(self, key: str):
        self._path(key).unlink(missing_ok=True)
