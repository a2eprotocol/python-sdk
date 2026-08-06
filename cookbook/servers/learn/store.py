"""
Persistent store for the learn plugin.

Mirrors prime-agent's harness state management:
  - harness_state.json  (snapshot of current policy + stats)
  - refinements.jsonl   (append-only history of refinement events)
  - feedbacks.jsonl     (append-only feedback log)
  - experiences.jsonl   (append-only experience log)
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, List, Optional


class HarnessState:
    """Mutable state snapshot persisted to harness_state.json."""

    def __init__(self):
        self.policy_name: str = "default"
        self.policy_version: str = "v1"
        self.checkpoint_uri: Optional[str] = None
        self.rollouts: Dict[str, Dict[str, Any]] = {}
        self.stats: Dict[str, Dict[str, Any]] = {}
        self.scope: str = "local"  # local | global
        self.created_at: float = 0.0
        self.updated_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "policy_name": self.policy_name,
            "policy_version": self.policy_version,
            "checkpoint_uri": self.checkpoint_uri,
            "rollouts": self.rollouts,
            "stats": self.stats,
            "scope": self.scope,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HarnessState":
        s = cls()
        s.policy_name = data.get("policy_name", "default")
        s.policy_version = data.get("policy_version", "v1")
        s.checkpoint_uri = data.get("checkpoint_uri")
        s.rollouts = data.get("rollouts", {})
        s.stats = data.get("stats", {})
        s.scope = data.get("scope", "local")
        s.created_at = data.get("created_at", 0.0)
        s.updated_at = data.get("updated_at", 0.0)
        return s


class JsonlStore:
    """Append-only JSONL store for audit trails."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if not os.path.exists(path):
            with open(path, "w") as f:
                pass  # create empty file

    def append(self, record: dict) -> None:
        with self._lock:
            with open(self.path, "a") as f:
                f.write(json.dumps(record) + "\n")

    def load_all(self) -> List[dict]:
        if not os.path.exists(self.path):
            return []
        records = []
        with self._lock:
            with open(self.path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
        return records

    def load_since(self, after_ts: float) -> List[dict]:
        return [
            r for r in self.load_all()
            if r.get("ts", 0) >= after_ts
        ]


class LearnStore:
    """
    File-backed store for the learn plugin.

    Mirrors prime-agent's harness state + refinements.jsonl pattern:
      - harness_state.json  — current policy + aggregated stats
      - refinements.jsonl   — append-only refinement history
      - feedbacks.jsonl     — append-only feedback log
      - experiences.jsonl   — append-only experience log
    """

    def __init__(self, root: str):
        self.root = root
        os.makedirs(root, exist_ok=True)

        self.state_path = os.path.join(root, "harness_state.json")
        self.refinements_path = os.path.join(root, "refinements.jsonl")
        self.feedbacks_path = os.path.join(root, "feedbacks.jsonl")
        self.experiences_path = os.path.join(root, "experiences.jsonl")

        # Load or initialize harness state
        self.state = self._load_state()

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> HarnessState:
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r") as f:
                    data = json.load(f)
                return HarnessState.from_dict(data)
            except (json.JSONDecodeError, OSError):
                pass
        return HarnessState()

    def save_state(self) -> None:
        self.state.updated_at = _now()
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state.to_dict(), f, indent=2)
        os.replace(tmp, self.state_path)

    # ------------------------------------------------------------------
    # Refinement history
    # ------------------------------------------------------------------

    def append_refinement(self, record: dict) -> None:
        record.setdefault("ts", _now())
        self.refinements_path  # ensure dir exists
        JsonlStore(self.refinements_path).append(record)

    def load_refinements(self) -> List[dict]:
        return JsonlStore(self.refinements_path).load_all()

    def load_refinements_since(self, after_ts: float) -> List[dict]:
        return JsonlStore(self.refinements_path).load_since(after_ts)

    # ------------------------------------------------------------------
    # Feedback log
    # ------------------------------------------------------------------

    def append_feedback(self, record: dict) -> None:
        record.setdefault("ts", _now())
        JsonlStore(self.feedbacks_path).append(record)

    def load_feedbacks(self) -> List[dict]:
        return JsonlStore(self.feedbacks_path).load_all()

    # ------------------------------------------------------------------
    # Experience log
    # ------------------------------------------------------------------

    def append_experience(self, record: dict) -> None:
        record.setdefault("ts", _now())
        JsonlStore(self.experiences_path).append(record)

    def load_experiences(self) -> List[dict]:
        return JsonlStore(self.experiences_path).load_all()

    # ------------------------------------------------------------------
    # Merge (for multi-instance scenarios)
    # ------------------------------------------------------------------

    def merge_refinements(self, other_refinements: List[dict]) -> int:
        """Merge external refinements, skipping duplicates by id."""
        existing_ids = {
            r.get("refinement_id")
            for r in self.load_refinements()
        }
        added = 0
        for r in other_refinements:
            rid = r.get("refinement_id")
            if rid and rid not in existing_ids:
                self.append_refinement(r)
                added += 1
        return added


def _now() -> float:
    import time
    return time.time()