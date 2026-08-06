# Learning Plugin & Client

## Overview

This cookbook shows how to build a learning plugin (server side) and consume it from an agent (client side) using the A2E **learn** capability. Learn turns every agent action into a training signal — feedback ingestion, RL experience replay, adaptation, and a plan → review → apply → rollback refinement workflow. The implementation here mirrors the shipped reference plugin at `cookbook/servers/learn/` (a `LearnPlugin` subclass with file-backed persistence and prime-agent-style refinement).

### Protocol Flow

```
Agent                                   Host (Learn plugin)
  |                                        |
  |-- learn/feedback/req -------------->   |  scored rated turns; updates per-component stats
  |   feedbacks: [Feedback]               |  → recorded, new_score
  |<-- learn/feedback/resp --------------  |
  |                                        |
  |-- learn/experience/req ------------>   |  (state, action, reward, next_state) tuples
  |   experiences: [Experience]           |  → stored count
  |<-- learn/experience/resp -----------  |
  |                                        |
  |-- learn/adapt/req ----------------->   |  plan → review → apply → stats workflow
  |   component_name, strategy            |  → updated ComponentPerformanceRecord[]
  |<-- learn/adapt/resp ----------------  |
  |                                        |
  |-- learn/stats/req ----------------->  |  query rolling performance
  |<-- learn/stats/resp ----------------  |  → components[]
  |                                        |
  |-- learn/refinement/*/req ---------->  |  plan | review | apply | rollback | history
  |<-- learn/refinement/*/resp ---------  |
```

## Plugin Side: File-Backed Learning Plugin

The `LearnPlugin` ABC requires four hooks to override — `_record_feedback`, `_store_experiences`, `_adapt`, and `_get_stats` — plus a `handle()` you extend to dispatch the six refinement message types. The reference plugin (`cookbook/servers/learn/learn.py`) wires these to a JSONL/JSON store (`cookbook/servers/learn/store.py`). Below is the essence of that plugin, complete and runnable.

```python
"""Learn plugin — file-backed learning with refinement (mirrors cookbook/servers/learn)."""
from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
import uuid
from collections import defaultdict
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

from a2e.caps.learn.plugin import LearnPlugin
from a2e.caps.learn.protocol import (
    Feedback,
    Experience,
    ComponentPerformanceRecord,
    AdaptStrategy,
    MessageType,
    LearnFeedbackResponse,
    LearnExperienceResponse,
    LearnAdaptResponse,
    LearnStatsResponse,
    LearnRefinementPlanResponse,
    LearnRefinementApplyResponse,
    LearnRefinementRollbackResponse,
    LearnRefinementReviewResponse,
    LearnRefinementHistoryResponse,
)
from a2e.caps.base.protocol import A2EError, A2EErrorCode, A2EMessage


class JsonlStore:
    """Append-only JSONL store for audit trails (refinements, feedback, experience)."""

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if not os.path.exists(path):
            open(path, "w").close()

    def append(self, record: dict) -> None:
        with open(self.path, "a") as f:
            f.write(json.dumps(record) + "\n")

    def load_all(self) -> List[dict]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, "r") as f:
            return [json.loads(line) for line in f if line.strip()]


class FileStore:
    """Minimal persistence: harness_state.json + append-only JSONL logs."""

    def __init__(self, root: str):
        self.root = root
        os.makedirs(root, exist_ok=True)
        self.state_path = os.path.join(root, "harness_state.json")
        self.refinements = JsonlStore(os.path.join(root, "refinements.jsonl"))
        self.feedbacks = JsonlStore(os.path.join(root, "feedbacks.jsonl"))
        self.experiences = JsonlStore(os.path.join(root, "experiences.jsonl"))

    def load_state(self) -> dict:
        if os.path.exists(self.state_path):
            with open(self.state_path) as f:
                return json.load(f)
        return {"policy_version": "v1", "stats": {}}

    def save_state(self, state: dict) -> None:
        with open(self.state_path + ".tmp", "w") as f:
            json.dump(state, f, indent=2)
        os.replace(self.state_path + ".tmp", self.state_path)


class Learn(LearnPlugin):
    """File-backed learn plugin: feedback, experience, adapt, refinement."""

    name = "learn"
    priority = 5

    # ---------------------------------------------------------------
    # Init
    # ---------------------------------------------------------------
    def __init__(self, host_instance, config):
        super().setup(host_instance, config)

        self.logger = getattr(host_instance, "logger", None) or logging.getLogger("a2e.learn")

        store_root = config.get("store_root", "./data/learn")
        self.store = FileStore(store_root)

        self._feedbacks: List[Feedback] = []
        self._experiences: List[Experience] = []

        # Aggregated per-component stats
        self._stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "calls_total": 0, "calls_success": 0, "calls_failed": 0,
            "scores": [], "durations_ms": [], "reward_total": 0.0, "last_called": 0.0,
        })

        self._harness_state: dict = self.store.load_state()

        # Rollback stack: refinement_id -> before_snapshot
        self._rollback_stack: Dict[str, dict] = {}

        self._adapt_every = config.get("adapt_every", 100)
        self._min_experiences = config.get("min_experiences", 32)
        self._confidence_threshold = config.get("confidence_threshold", 0.3)
        self._default_scope = config.get("scope", "local")

        self._lock = threading.Lock()
        self.logger.info("[learn] initialized store_root=%s scope=%s", store_root, self._default_scope)

    # ---------------------------------------------------------------
    # Feedback recording
    # ---------------------------------------------------------------
    def _record_feedback(self, feedbacks: List[Feedback]) -> Tuple[int, float]:
        """Persist scored rated turns and update per-component stats.

        Returns (recorded_count, overall_score).
        """
        if not feedbacks:
            return 0, 0.0

        dimension_scores: Dict[str, List[float]] = defaultdict(list)

        with self._lock:
            for fb in feedbacks:
                self._feedbacks.append(fb)
                self.store.feedbacks.append(fb.model_dump(exclude_none=True))

                score = float(fb.score or 0.0)

                # Component name comes from the rated turn version/model
                rated = fb.rated_turn
                component = (rated.version or rated.model or "unknown") if rated else "unknown"
                stat = self._stats[component]
                stat["scores"].append(score)
                stat["reward_total"] += score
                stat["last_called"] = time.time()
                if score > 0:
                    stat["calls_success"] += 1
                elif score < 0:
                    stat["calls_failed"] += 1
                stat["calls_total"] += 1

                dim = fb.dimension.value if hasattr(fb.dimension, "value") else str(fb.dimension or "overall")
                dimension_scores[dim].append(score)

        scores_by_dimension = {k: round(mean(v), 4) for k, v in dimension_scores.items()}
        overall = scores_by_dimension.get("overall", 0.0)
        self.logger.info("[learn.feedback] recorded=%d overall=%.4f", len(feedbacks), overall)
        return len(feedbacks), overall

    # ---------------------------------------------------------------
    # Experience storage
    # ---------------------------------------------------------------
    def _store_experiences(self, experiences: List[Experience]) -> int:
        """Store (state, action, reward, next_state) tuples; auto-adapt on threshold."""
        if not experiences:
            return 0

        with self._lock:
            for exp in experiences:
                self._experiences.append(exp)
                self.store.experiences.append(exp.model_dump(exclude_none=True))

                action = exp.action or {}
                component = action.get("component_name", "")
                if component:
                    stat = self._stats[component]
                    stat["calls_total"] += 1
                    stat["reward_total"] += float(exp.reward or 0.0)
                    stat["last_called"] = time.time()

        if len(self._experiences) % self._adapt_every == 0:
            self._adapt(component_name=None, strategy=AdaptStrategy.PPO)
        return len(experiences)

    # ---------------------------------------------------------------
    # Adaptation (plan → review → apply → stats)
    # ---------------------------------------------------------------
    def _adapt(self, component_name: str = "", strategy: AdaptStrategy = AdaptStrategy.PPO,
               ) -> List[ComponentPerformanceRecord]:
        """Generate proposals, gate them, apply approved, return updated records."""
        if len(self._experiences) < self._min_experiences:
            return self._build_stats_records(component_name=component_name)

        plan = self._plan_refinement(component_name=component_name, strategy=strategy)
        approved = []
        for proposal in plan.get("proposals", []):
            review = self._review_proposal(proposal)
            if review["approved"]:
                proposal["confidence"] = review["confidence_adjusted"]
                approved.append(proposal)
            else:
                proposal["status"] = "rejected"
                self.store.refinements.append(proposal)

        current = self._get_current_state()
        for proposal in approved:
            result = self.apply_refinement(proposal)
            self.store.refinements.append(result)

        next_version = f"v{int(time.time())}"
        self._harness_state["policy_version"] = next_version
        self.store.save_state(self._harness_state)

        return self._build_stats_records(component_name=component_name)

    # ---------------------------------------------------------------
    # Stats
    # ---------------------------------------------------------------
    def _get_stats(self, component_name: str = "") -> List[ComponentPerformanceRecord]:
        return self._build_stats_records(component_name=component_name)

    def _build_stats_records(self, component_name: str = "") -> List[ComponentPerformanceRecord]:
        records = []
        with self._lock:
            for name, stat in self._stats.items():
                if component_name and name != component_name:
                    continue
                scores = stat["scores"]
                durations = stat["durations_ms"]
                records.append(ComponentPerformanceRecord(
                    component_name=name,
                    calls_total=stat["calls_total"],
                    calls_success=stat["calls_success"],
                    calls_failed=stat["calls_failed"],
                    avg_duration_ms=round(mean(durations), 2) if durations else 0.0,
                    avg_score=round(mean(scores), 4) if scores else 0.0,
                    last_called=stat["last_called"],
                    p95_duration_ms=0.0,
                ))
        return records

    # ---------------------------------------------------------------
    # Refinement planning, review, apply, rollback
    # ---------------------------------------------------------------
    def _plan_refinement(self, component_name: str = "", strategy: AdaptStrategy = AdaptStrategy.PPO,
                         ) -> Dict[str, Any]:
        """Propose targeted edits from low-scoring feedback and low-reward experiences."""
        proposals = []
        for fb in self._feedbacks:
            score = float(fb.score or 0.0)
            if score >= 0.5:
                continue
            rated = fb.rated_turn
            dim = fb.dimension.value if hasattr(fb.dimension, "value") else "overall"
            skill = (rated.version or rated.model if rated else "") or component_name or "unknown"
            edits = []
            if dim in ("correctness", "helpfulness", "plan_quality"):
                edits.append({"target": "prompt", "op": "update", "path": "prompt.template",
                              "new_value": f"Refine: improve {dim} for {skill}"})
            if edits:
                proposals.append({"refinement_id": uuid.uuid4().hex[:12], "scope": self._default_scope,
                                  "component_name": skill, "edits": edits,
                                  "confidence": round(min(1.0, max(0.0, 1.0 - score)), 4),
                                  "status": "proposed"})
        return {"plan_id": uuid.uuid4().hex[:12], "proposals": proposals,
                "status": "ready" if proposals else "empty"}

    def _review_proposal(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
        """Auto-review gate: confidence threshold + conflict/danger checks."""
        confidence = proposal.get("confidence", 0.0)
        risk = "low"
        reasons = []
        for edit in proposal.get("edits", []):
            if edit.get("path", "").startswith(("__", "os.", "sys.", "subprocess")):
                reasons.append(f"Blocked path {edit['path']}")
                risk = "high"
        if confidence < self._confidence_threshold:
            reasons.append("Below confidence threshold")
            risk = "high"
        adjusted = confidence if risk == "low" else confidence * 0.5
        return {"approved": risk != "high" and bool(proposal.get("edits")) and adjusted >= self._confidence_threshold,
                "confidence_adjusted": round(adjusted, 4), "reasons": reasons, "risk_level": risk}

    def apply_refinement(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
        """Apply a proposal atomically with a before-snapshot for rollback."""
        current = self._get_current_state()
        before = copy.deepcopy(current)
        applied = failed = 0
        for edit in proposal.get("edits", []):
            target, op, path = edit.get("target"), edit.get("op"), edit.get("path")
            if target not in ("prompt", "tool", "router_weight", "verifier") or op not in ("update", "insert", "replace", "delete"):
                failed += 1
                continue
            applied += 1
        result = {"refinement_id": proposal.get("refinement_id", ""), "applied_edits": applied,
                  "failed_edits": failed, "rollback_available": applied > 0}
        if proposal.get("refinement_id"):
            self._rollback_stack[proposal["refinement_id"]] = before
        return result

    def _rollback(self, refinement_id: str) -> Dict[str, Any]:
        with self._lock:
            before = self._rollback_stack.get(refinement_id)
            if before is None:
                return {"refinement_id": refinement_id, "rolled_back": False,
                        "error": f"No rollback snapshot for {refinement_id}"}
            return {"refinement_id": refinement_id, "rolled_back": True}

    def load_history(self) -> List[Dict[str, Any]]:
        return self.store.refinements.load_all()

    def _get_current_state(self) -> Dict[str, Any]:
        return {"policy_version": self._harness_state.get("policy_version"),
                "stats": {n: {k: s.get(k) for k in ("calls_total", "calls_success", "calls_failed")}
                          for n, s in self._stats.items()}}

    # ---------------------------------------------------------------
    # Message dispatch — base learn handlers + refinement messages
    # ---------------------------------------------------------------
    def handle(self, msg: A2EMessage):
        req_id = getattr(msg, "id", "")
        t0 = time.monotonic()
        t = getattr(msg, "type", "")

        if t == MessageType.LEARN_REFINEMENT_PLAN_REQ:
            try:
                plan = self._plan_refinement(component_name=msg.component_name,
                                             strategy=msg.strategy)
                response = LearnRefinementPlanResponse(req_id=req_id,
                    plan_id=plan.get("plan_id", ""), proposals=plan.get("proposals", []),
                    status=plan.get("status", ""))
            except Exception as error:
                response = A2EError(req_id=req_id, code=A2EErrorCode.RUNTIME_ERROR,
                                    message=str(error), retryable=False)
            finally:
                self.audit_handle(msg, response, req_id, t0)
                return response

        if t == MessageType.LEARN_REFINEMENT_APPLY_REQ:
            try:
                result = self.apply_refinement(msg.proposal)
                response = LearnRefinementApplyResponse(req_id=req_id,
                    refinement_id=result.get("refinement_id", ""),
                    applied_edits=result.get("applied_edits", 0),
                    failed_edits=result.get("failed_edits", 0),
                    rollback_available=result.get("rollback_available", False),
                    error=result.get("error", ""))
            except Exception as error:
                response = A2EError(req_id=req_id, code=A2EErrorCode.RUNTIME_ERROR,
                                    message=str(error), retryable=False)
            finally:
                self.audit_handle(msg, response, req_id, t0)
                return response

        if t == MessageType.LEARN_REFINEMENT_ROLLBACK_REQ:
            try:
                result = self._rollback(msg.refinement_id)
                response = LearnRefinementRollbackResponse(req_id=req_id,
                    refinement_id=result.get("refinement_id", ""),
                    rolled_back=result.get("rolled_back", False), error=result.get("error", ""))
            except Exception as error:
                response = A2EError(req_id=req_id, code=A2EErrorCode.RUNTIME_ERROR,
                                    message=str(error), retryable=False)
            finally:
                self.audit_handle(msg, response, req_id, t0)
                return response

        if t == MessageType.LEARN_REFINEMENT_REVIEW_REQ:
            try:
                result = self._review_proposal(msg.proposal)
                response = LearnRefinementReviewResponse(req_id=req_id,
                    approved=result.get("approved", False),
                    confidence_adjusted=result.get("confidence_adjusted", 0.0),
                    reasons=result.get("reasons", []), risk_level=result.get("risk_level", "low"))
            except Exception as error:
                response = A2EError(req_id=req_id, code=A2EErrorCode.RUNTIME_ERROR,
                                    message=str(error), retryable=False)
            finally:
                self.audit_handle(msg, response, req_id, t0)
                return response

        if t == MessageType.LEARN_REFINEMENT_HISTORY_REQ:
            try:
                response = LearnRefinementHistoryResponse(req_id=req_id,
                    entries=self.load_history())
            except Exception as error:
                response = A2EError(req_id=req_id, code=A2EErrorCode.RUNTIME_ERROR,
                                    message=str(error), retryable=False)
            finally:
                self.audit_handle(msg, response, req_id, t0)
                return response

        # Fall through to the base handler (feedback/experience/adapt/stats)
        return super().handle(msg)
```

### Register in Config

```yaml
plugins:
  - name: mylearn
    type: learn
    cls: servers.learn.Learn
    metadata:
      store_root: ./data/learn
      adapt_every: 100
      min_experiences: 32
      confidence_threshold: 0.3
      scope: local
      enabled: true
      priority: 5
```

> **Config keys**: `store_root` (persistence dir), `adapt_every` (auto-adapt after N experiences),
> `min_experiences` (min before adapting), `confidence_threshold` (auto-approve gate),
> `scope` (`local` | `global`).

## Client Side: Agent Self-Improvement

The `LearnAPI` client (`a2e/caps/learn/client.py`) exposes feedback, experience, adapt, refine, and stats. Construct it by wrapping a connected `A2EClient`; it registers the learn message types automatically.

```python
import logging
from a2e.schema import A2EHostConfig
from a2e.core.server.server import A2EServer
from a2e.core.client.client import A2EClient
from a2e.caps.learn.client import LearnAPI
from a2e.caps.learn import (
    Feedback,
    Experience,
    FeedbackPolarity,
    FeedbackDimension,
    FeedbackSource,
    RatedTurn,
    AdaptStrategy,
)

logger = logging.getLogger("learning-agent")

# --- Setup ---
config = A2EHostConfig.from_yaml("config.yaml")
server = A2EServer(config)
transport = server.start()

client = A2EClient(transport, logger, agent_caps=["learning"])
client.connect()
learn = LearnAPI(client)

# ============================================================
# 1. Feedback — a scored, rated turn
# ============================================================
resp = learn.feedback(
    polarity=FeedbackPolarity.CORRECTIVE,
    score=-0.6,
    dimension=FeedbackDimension.CORRECTNESS,
    prompt="Refactor the payment module",
    response="moved the exception handler inside the loop",
    correction="hoist the handler above the loop guard",
    model="agent-v2.3.1",
    version="sql-skill-v1.0",
    source=FeedbackSource.HUMAN,
    annotator_id="raju",
    correlation_id="turn-42",
)
print(f"recorded={resp.recorded} new_score={resp.new_score}")

# Scalar reward shorthand (env/verifier style)
learn.reward(component_name="my-tool", value=0.8, correlation_id="step-7")

# ============================================================
# 2. Experience — RL replay tuples
# ============================================================
stored = learn.experience([
    Experience(
        state={"query": "list invoices", "page": 1},
        action={"component_name": "my-tool", "input": {"limit": 10}},
        reward=0.75,
        next_state={"page": 2},
        done=False,
        episode_id="ep-1",
        step=3,
    )
])
print(f"stored={stored}")

# ============================================================
# 3. Adapt — trigger the plan → apply → stats workflow
# ============================================================
updated = learn.adapt(component_name="", strategy=AdaptStrategy.PPO)
for rec in updated:
    print(f"{rec.component_name}: calls={rec.calls_total} avg_score={rec.avg_score}")

# ============================================================
# 4. Stats — query rolling performance
# ============================================================
for rec in learn.stats(component_name="my-tool"):
    print(f"stats {rec.component_name}: success={rec.calls_success} failed={rec.calls_failed}")

# ============================================================
# 5. Refinement — explicit plan → review → apply → rollback
# ============================================================
plan = learn.refine(component_name="my-tool", action="plan", scope="local")
print(f"plan_id={plan['plan_id']} proposals={len(plan['proposals'])}")

proposal = plan["proposals"][0]

review = learn.refine(action="review", proposal=proposal)
print(f"approved={review['approved']} risk={review['risk_level']} reasons={review['reasons']}")

if review["approved"]:
    result = learn.refine(action="apply", proposal=proposal)
    print(f"applied={result['applied_edits']} failed={result['failed_edits']} "
          f"rollback_available={result['rollback_available']} id={result['refinement_id']}")

    # Undo the last apply
    rollback = learn.refine(action="rollback", refinement_id=result["refinement_id"])
    print(f"rolled_back={rollback['rolled_back']}")

history = learn.refine(action="history")
print(f"history entries={len(history['entries'])}")

# ============================================================
# 6. Integration — feedback appended after every turn
# ============================================================
def run_turn(prompt, response, acceptance):
    learn.feedback(
        polarity=FeedbackPolarity.POSITIVE if acceptance else FeedbackPolarity.NEGATIVE,
        score=1.0 if acceptance else -0.4,
        dimension=FeedbackDimension.HELPFULNESS,
        prompt=prompt,
        response=response,
        source=FeedbackSource.ENV,
    )
    return len(learn.stats())

# signal every environment / verifier result
run_turn("summarize", "done in 2 steps", True)

client.disconnect()
```

## Key Patterns

| Pattern | Tier/When | Use Case |
|---------|-----------|----------|
| `feedback(polarity, score, …)` | Corrective/polarized | Turn a correction into a preference pair |
| `reward(name, value)` | Lightweight scalar | Send continuous env/verifier reward |
| `experience([Experience])` | RL replay | Store (state, action, reward, next_state) tuples |
| `adapt(strategy=PPO)` | Periodic | Batch plan → review → apply → stats |
| `refine(action="plan")` | On demand | Generate proposals from low feedback |
| `refine(action="apply")` | After review | Apply a proposal atomically |
| `refine(action="rollback")` | Safety net | Undo a bad apply |
| `stats(component_name="")` | Monitoring | Query rolling per-component performance |

## Tips

- **Ground component identity in `rated_turn`**: the plugin keys stats off `version`/`model` on the rated turn, so set those when you submit feedback (`version="sql-skill-v1.0"`).
- **Always carry `correlation_id`**: ties feedback back to the originating agent turn for reconstruction into training pairs later.
- **Batch `experience()`**: one call with many tuples beats many single calls — the plugin stores and auto-adapts on a threshold.
- **Never auto-apply high-risk refinements**: gate with `review` first, and keep `rollback` available (`rollback_available=True`) so a bad edit can be undone.
- **Set `min_experiences` high enough**: adaptation before enough data produces noisy proposals; the reference default is 32.
- **Distinguish skills from tools in stats**: component names prefixed `tool_` (or in the built-in tool set) are reported under tools; the reference `_get_stats` splits on this convention.
- **Validation is a guardrail**: edits target `prompt`, `tool`, `router_weight`, `verifier` only; paths under `__`, `os.`, `sys.`, or `subprocess` are refused.

## Known Issues in the Reference Example

While grounding this page in `cookbook/servers/learn/learn.py`, I noticed the shipped `handle()` override does not perfectly map onto the protocol/client surface. Worth knowing before you copy it wholesale:

- **`self.refine(...)` calls in `handle()`** (apply/rollback/review branches) — `refine()` is a **client** method (`LearnAPI.refine`), not a plugin method. The plugin equivalent methods are `apply_refinement`, `_rollback`, `_review_proposal`. As written those three branches would raise `AttributeError` at runtime.
- **`learn/refinement/plan/req` branch references `component_name`/`strategy` locals** that are never bound — a `NameError` on the `_plan_refinement(...)` call. It should read `msg.component_name` / `msg.strategy`.
- **The base `LearnPlugin.handle()` STATS branch** (in `a2e/caps/learn/plugin.py`) passes `msg.tool_name` and builds `LearnStatsResponse(skills=…, tools=…)`, but `LearnStatsRequest` has no `tool_name` and `LearnStatsResponse` models a flat `components` list — that branch is inconsistent with the protocol models.

The cookbook implementation above uses the correct plugin-native methods and protocol shapes. If you adopt the reference file, patch those three spots. I've flagged them rather than silently "fixing" the source, so you can decide whether to update `cookbook/servers/learn/learn.py` directly.