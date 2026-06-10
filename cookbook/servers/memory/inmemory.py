import pdb
import uuid
import json
import hashlib
from typing import List, Optional
from collections import OrderedDict
from a2e.caps.memory import (
    MemoryPlugin,
    MemoryTier,
    MemoryEntry
)


def to_list_dict(store: dict) -> list[dict]:
    return [entry.model_dump() for entry in store.values()]


def make_hash_key(data: dict) -> str:
    """
    Create a stable, hashable key from a dict.
    Handles nested dicts/lists.
    """

    def normalize(obj):
        if isinstance(obj, dict):
            return {k: normalize(obj[k]) for k in sorted(obj)}
        elif isinstance(obj, list):
            return [normalize(x) for x in obj]
        else:
            return obj

    normalized = normalize(data)

    # deterministic JSON string
    s = json.dumps(normalized, separators=(",", ":"), ensure_ascii=False)

    # hash
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class InMemoryPlugin(MemoryPlugin):

    def __init__(self, host_instance, config):
        super().__init__(host_instance, config)

        self.working = OrderedDict()
        self.episodic = {}
        self.semantic = {}

        self.working_limit = config.get("working_limit", 50)
        self.semantic_limit = config.get("semantic_limit", 50)
        self.episodic_limit = config.get("episodic_limit", 50)

    def on_init(
        self,
        namespace: str,
        scope: dict,
        metadata: Optional[dict] = None,
    ):
        """Create a new memory session and return (memory_id, backend_object)."""
        memory_id = str(uuid.uuid4())
        return memory_id, self

    # -----------------------------
    def _score(self, entry: MemoryEntry, req) -> float:
        """
        Compute a relevance score between a memory entry and a query request.

        Scoring heuristics:
        - Exact key hash match: +1.0
        - Exact raw key dict match: +1.0
        - Partial dict overlap: proportional score
        - Tag overlap: proportional score
        - Tier match: +0.25

        Final score is normalized roughly into [0, 1+].
        """

        score = 0.0

        # -----------------------------
        # Tier match
        # -----------------------------
        if getattr(req, "tier", None):
            if entry.tier == req.tier:
                score += 0.25
            else:
                return 0.0

        # -----------------------------
        # Key similarity
        # -----------------------------
        if getattr(req, "keys", None):

            entry_hash = make_hash_key(entry.key)

            best_key_score = 0.0

            for k in req.keys:

                # Exact hash match
                if isinstance(k, str) and k == entry_hash:
                    best_key_score = max(best_key_score, 1.0)

                # Exact dict match
                elif isinstance(k, dict):

                    if k == entry.key:
                        best_key_score = max(best_key_score, 1.0)

                    else:
                        # Partial dict overlap
                        overlap = 0
                        total = len(k)

                        for kk, vv in k.items():
                            if kk in entry.key and entry.key[kk] == vv:
                                overlap += 1

                        if total > 0:
                            partial = overlap / total
                            best_key_score = max(best_key_score, partial)

            score += best_key_score

        # -----------------------------
        # Tag similarity
        # -----------------------------
        if getattr(req, "tags", None):

            entry_tags = set(entry.tags or [])
            req_tags = set(req.tags or [])

            if req_tags:
                overlap = len(entry_tags.intersection(req_tags))
                tag_score = overlap / len(req_tags)

                score += tag_score

        return round(score, 4)

    def _match(self, entry: MemoryEntry, req) -> bool:
        """
        Match a memory entry against a query request.

        Matching rules:
        - req.keys:
            Matches against the hashed memory key OR raw entry.key dict.
        - req.tags:
            Any overlap with entry.tags.
        - req.tier:
            Entry tier must match.
        """

        # Tier filter
        if getattr(req, "tier", None):
            if entry.tier != req.tier:
                return False

        # Key filter
        if getattr(req, "keys", None):
            entry_hash = make_hash_key(entry.key)

            matched = False
            for k in req.keys:
                # direct hash match
                if k == entry_hash:
                    matched = True
                    break

                # raw dict match
                if isinstance(k, dict) and k == entry.key:
                    matched = True
                    break

            if not matched:
                return False

        # Tag filter
        if getattr(req, "tags", None):
            entry_tags = set(entry.tags or [])
            req_tags = set(req.tags)

            if not entry_tags.intersection(req_tags):
                return False

        return True

    # -----------------------------
    def _get_store(self, tier):
        if tier == MemoryTier.WORKING.value:
            return self.working
        elif tier == MemoryTier.SEMANTIC.value:
            return self.semantic
        elif tier == MemoryTier.EPISODIC.value:
            return self.episodic
        return self.episodic

    # -----------------------------
    def on_store(self, memory, entries: List[MemoryEntry]):
        stored, errors = [], []
        for e in entries:
            try:
                store = self._get_store(e.tier)
                key = make_hash_key(e.key)
                store[key] = e

                if e.tier == MemoryTier.WORKING.value:
                    while len(self.working) > self.working_limit:
                        self.working.popitem(last=False)
                elif e.tier == MemoryTier.SEMANTIC.value:
                    while len(self.semantic) > self.semantic_limit:
                        self.semantic.popitem(last=False)
                elif e.tier == MemoryTier.EPISODIC.value:
                    while len(self.episodic) > self.episodic_limit:
                        self.episodic.popitem(last=False)

                stored = to_list_dict(store)
            except Exception as ex:
                errors.append(str(ex))

        return stored, errors

    # -----------------------------
    def on_retrieve(self, memory, req) -> List[MemoryEntry]:
        results = []

        stores = []
        if req.tier:
            stores = [self._get_store(req.tier)]
        else:
            stores = [self.working, self.episodic, self.semantic]

        for store in stores:
            for e in store.values():
                if self._match(e, req):
                    e.score = self._score(e, req)
                    results.append(e)

        results.sort(key=lambda x: x.score, reverse=True)
        return results[: req.limit]

    # -----------------------------
    def on_forget(self, memory, req):
        deleted = 0

        stores = []
        if req.tier:
            stores = [self._get_store(req.tier)]
        else:
            stores = [self.working, self.episodic, self.semantic]

        for store in stores:
            keys = list(store.keys())

            for k in keys:
                e = store[k]

                if req.keys and k in req.keys:
                    del store[k]
                    deleted += 1
                elif req.tags and any(t in e.tags for t in req.tags):
                    del store[k]
                    deleted += 1

        return deleted
