"""
Learn plugin — cookbook server implementation.

Reuses existing a2e protocol primitives (Feedback, Experience,
ComponentPerformanceRecord) and adds prime-agent-style refinement:

  plan → apply → rollback → history

Features:
  - File-backed persistence (harness_state.json + refinements.jsonl)
  - Scope support (local / global)
  - Refinement planning from low-scoring feedback
  - Auto-review gate (confidence + conflict detection)
  - Atomic apply with before/after snapshots
  - Rollback via snapshot restore
  - Refinement history (refinements.jsonl)
  - Validation of edits before apply
  - Proper ComponentPerformanceRecord tracking
"""
from __future__ import annotations

import copy
import json
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
    LearnAdaptRequest,
    LearnFeedbackResponse,
    LearnExperienceResponse,
    LearnAdaptResponse,
    LearnStatsResponse,
)

from cookbook.servers.learn.store import LearnStore, HarnessState


class Learn(LearnPlugin):
    """
    Server-side learning plugin with prime-agent-style refinement.

    Responsibilities:
      - ingest feedback (score, dimension, polarity)
      - store trajectories / experiences
      - plan refinements from low-scoring feedback
      - auto-review proposals (confidence + conflict gate)
      - apply edits atomically with before/after snapshots
      - rollback failed or harmful edits
      - persist refinement history to refinements.jsonl
      - expose runtime performance metrics

    Config keys:
      adapt_every           — trigger adaptation after N experiences (default 100)
      min_experiences       — minimum experiences before adapting (default 32)
      store_root            — directory for persistence (default ./data/learn)
      scope                 — default refinement scope: local | global (default local)
      confidence_threshold  — minimum confidence for auto-approve (default 0.3)
    """

    name = "learn"
    priority = 5

    # =====================================================
    # Init
    # =====================================================

    def __init__(self, host_instance, config):
        super().setup(host_instance, config)

        self.logger = getattr(host_instance, "logger", None)
        if self.logger is None:
            import logging
            self.logger = logging.getLogger("a2e.learn")

        # ---------------------------------------------
        # Persistence
        # ---------------------------------------------
        store_root = config.get("store_root", "./data/learn")
        self.store = LearnStore(store_root)

        # ---------------------------------------------
        # In-memory caches (mirrors store)
        # ---------------------------------------------
        self._feedbacks: List[Feedback] = []
        self._experiences: List[Experience] = []

        # ---------------------------------------------
        # Aggregated Performance Stats
        # ---------------------------------------------
        # Keyed by component_name or tool_name
        self._stats = defaultdict(
            lambda: {
                "calls_total": 0,
                "calls_success": 0,
                "calls_failed": 0,
                "scores": [],
                "durations_ms": [],
                "reward_total": 0.0,
                "last_called": 0.0,
            }
        )

        # ---------------------------------------------
        # Harness State (mirrors prime-agent's harness_state.json)
        # ---------------------------------------------
        self._harness_state: HarnessState = self.store.state

        # ---------------------------------------------
        # Rollback Stack: refinement_id -> before_snapshot
        # ---------------------------------------------
        self._rollback_stack: Dict[str, Dict[str, Any]] = {}

        # ---------------------------------------------
        # Adapt Config
        # ---------------------------------------------
        self._adapt_every = config.get("adapt_every", 100)
        self._min_experiences = config.get("min_experiences", 32)
        self._confidence_threshold = config.get(
            "confidence_threshold", 0.3
        )
        self._default_scope = config.get("scope", "local")

        # ---------------------------------------------
        # Thread Safety
        # ---------------------------------------------
        self._lock = threading.Lock()

        self.logger.info(
            "[learn] initialized store_root=%s scope=%s",
            store_root,
            self._default_scope,
        )

    # =====================================================
    # Feedback Recording
    # =====================================================

    def _record_feedback(
        self,
        feedbacks: List[Feedback],
    ) -> Tuple[int, float]:
        """
        Persist reward / feedback signals and update stats.

        Returns:
            (count, overall_score)
        """
        if not feedbacks:
            return 0, 0.0

        dimension_scores: Dict[str, List[float]] = defaultdict(list)

        with self._lock:
            for fb in feedbacks:
                self._feedbacks.append(fb)

                # Persist to file store
                self.store.append_feedback(
                    fb.model_dump(exclude_none=True)
                )

                score = float(fb.score or 0.0)

                # Determine component name from rated_turn
                rated_turn = fb.rated_turn
                component_name = "unknown"
                if rated_turn:
                    version = rated_turn.version or ""
                    model = rated_turn.model or ""
                    component_name = version if version else (model or "unknown")

                stat = self._stats[component_name]
                stat["scores"].append(score)
                stat["reward_total"] += score
                stat["last_called"] = time.time()

                if score > 0:
                    stat["calls_success"] += 1
                elif score < 0:
                    stat["calls_failed"] += 1
                stat["calls_total"] += 1

                dimension = (
                    fb.dimension.value
                    if hasattr(fb.dimension, "value")
                    else str(fb.dimension or "overall")
                )
                dimension_scores[dimension].append(score)

        scores_by_dimension = {
            k: round(mean(v), 4)
            for k, v in dimension_scores.items()
        }

        overall = scores_by_dimension.get("overall", 0.0)

        self.logger.info(
            "[learn.feedback] recorded=%d overall=%.4f dims=%s",
            len(feedbacks),
            overall,
            list(scores_by_dimension.keys()),
        )

        return len(feedbacks), overall

    # =====================================================
    # Experience Storage
    # =====================================================

    def _store_experiences(
        self,
        experiences: List[Experience],
    ) -> int:
        """
        Store RL transitions / trajectories.

        Experiences are heavier than feedback:
          - state
          - action (with component_name)
          - reward
          - next_state
          - done
        """
        if not experiences:
            return 0

        with self._lock:
            for exp in experiences:
                self._experiences.append(exp)

                # Persist to file store
                self.store.append_experience(
                    exp.model_dump(exclude_none=True)
                )

                action = exp.action or {}
                # Extract component_name from action
                component_name = action.get("component_name", "")
                if component_name:
                    stat = self._stats[component_name]
                    stat["calls_total"] += 1
                    stat["reward_total"] += float(exp.reward or 0.0)
                    stat["last_called"] = time.time()

                # Also check for components list in action
                for c in action.get("components", []):
                    stat = self._stats[c]
                    stat["calls_total"] += 1
                    stat["reward_total"] += float(exp.reward or 0.0)
                    stat["last_called"] = time.time()

                for t in action.get("tools", []):
                    stat = self._stats[t]
                    stat["calls_total"] += 1
                    stat["reward_total"] += float(exp.reward or 0.0)
                    stat["last_called"] = time.time()

        self.logger.info(
            "[learn.experience] stored=%d",
            len(experiences),
        )

        # Trigger adapt if threshold reached
        if len(self._experiences) % self._adapt_every == 0:
            try:
                self._adapt(
                    component_name=None,
                    strategy=AdaptStrategy.PPO,
                )
            except Exception:
                self.logger.exception("[learn.adapt] failed")

        return len(experiences)

    # =====================================================
    # Adaptation (with refinement planning)
    # =====================================================

    def _adapt(
        self,
        component_name: str = "",
        strategy: AdaptStrategy = AdaptStrategy.PPO,
    ) -> List[ComponentPerformanceRecord]:
        """
        Trigger adaptation with refinement planning.

        Flow mirrors prime-agent's refine_harness():
          1. refine(action="plan")  — generate proposals from feedback
          2. review_auto_refine() — auto-approve/reject gate
          3. apply_refinement()  — apply approved proposals atomically
          4. append_history()    — persist to refinements.jsonl
          5. update_harness_state() — save harness_state.json

        Returns list of ComponentPerformanceRecord for affected skills.
        """
        with self._lock:
            if len(self._experiences) < self._min_experiences:
                self.logger.info(
                    "[learn.adapt] skipped (not enough experiences: %d < %d)",
                    len(self._experiences),
                    self._min_experiences,
                )
                return self._build_stats_records(component_name=component_name)

        # -----------------------------------------
        # Step 1: Plan refinements from feedback
        # -----------------------------------------
        plan = self._plan_refinement(
            component_name=component_name,
            strategy=strategy,
        )

        if not plan.get("proposals"):
            self.logger.info(
                "[learn.adapt] no refinement proposals generated",
            )
            return self._build_stats_records(component_name=component_name)

        self.logger.info(
            "[learn.adapt] plan=%s proposals=%d",
            plan.get("plan_id", "unknown"),
            len(plan.get("proposals", [])),
        )

        # -----------------------------------------
        # Step 2: Auto-review gate
        # -----------------------------------------
        history = self.store.load_refinements()
        approved_proposals = []

        for proposal in plan.get("proposals", []):
            review = self._review_proposal(
                proposal,
                history=history,
            )

            self.logger.info(
                "[learn.review] proposal=%s approved=%s confidence=%.3f risk=%s",
                proposal.get("refinement_id", "unknown"),
                review["approved"],
                review["confidence_adjusted"],
                review["risk_level"],
            )

            if review["approved"]:
                proposal["confidence"] = review["confidence_adjusted"]
                approved_proposals.append(proposal)
            else:
                proposal["status"] = "rejected"
                self._append_refinement_history(proposal)

        # -----------------------------------------
        # Step 3: Apply approved proposals
        # -----------------------------------------
        current_state = self._get_current_state()

        for proposal in approved_proposals:
            # Validate all edits first
            valid, errors = self._validate_proposal(
                proposal,
                current_state,
            )
            if not valid:
                self.logger.warning(
                    "[learn.apply] proposal=%s validation failed: %s",
                    proposal.get("refinement_id", "unknown"),
                    errors,
                )
                proposal["status"] = "rejected"
                self._append_refinement_history(proposal)
                continue

            # Take before snapshot for rollback
            before_snapshot = copy.deepcopy(current_state)

            # Apply edits to current state
            applied, failed = self._apply_edits(
                proposal.get("edits", []),
                current_state,
            )

            # Save before snapshot for rollback
            self._rollback_stack[
                proposal.get("refinement_id", "")
            ] = before_snapshot

            # Record result
            proposal["status"] = (
                "applied" if applied > 0 else "failed"
            )
            proposal["applied_edits"] = applied
            proposal["failed_edits"] = failed
            self._append_refinement_history(proposal)

            self.logger.info(
                "[learn.apply] proposal=%s applied=%d failed=%d",
                proposal.get("refinement_id", "unknown"),
                applied,
                failed,
            )

        # -----------------------------------------
        # Step 4: Update harness state
        # -----------------------------------------
        self._update_harness_state(current_state)
        self.store.save_state()

        # -----------------------------------------
        # Step 5: Activate new policy version
        # -----------------------------------------
        next_version = f"v{int(time.time())}"
        self._harness_state.policy_version = next_version
        self._harness_state.checkpoint_uri = (
            f"s3://a2e/checkpoints/{next_version}"
        )
        self.store.save_state()

        self.logger.info(
            "[learn.adapt] activated policy=%s version=%s",
            self._harness_state.policy_name,
            next_version,
        )

        return self._build_stats_records(component_name=component_name)

    # =====================================================
    # Rollback
    # =====================================================

    def _rollback(
        self,
        refinement_id: str,
    ) -> Dict[str, Any]:
        """
        Rollback a previously applied refinement.

        Mirrors prime-agent's rollback_proposal():
          - Restore state from before-snapshot
          - Mark refinement as rolled_back in history
        """
        with self._lock:
            before_snapshot = self._rollback_stack.get(refinement_id)
            if before_snapshot is None:
                return {
                    "refinement_id": refinement_id,
                    "rolled_back": False,
                    "error": f"No rollback snapshot for {refinement_id}",
                }

            current_state = self._get_current_state()

            # Restore from snapshot
            current_state.clear()
            current_state.update(before_snapshot)

            # Update rollback stack
            self._rollback_stack[refinement_id] = copy.deepcopy(current_state)

            # Update harness state
            self._update_harness_state(current_state)
            self.store.save_state()

            # Record in history
            self._append_refinement_history({
                "refinement_id": refinement_id,
                "scope": self._default_scope,
                "action": "rollback",
                "rolled_back": True,
                "ts": time.time(),
            })

            return {
                "refinement_id": refinement_id,
                "rolled_back": True,
                "before_snapshot": before_snapshot,
                "after_snapshot": copy.deepcopy(current_state),
            }

    # =====================================================
    # Stats
    # =====================================================

    def _get_stats(
        self,
        component_name: str = "",
        tool_name: str = "",
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Return routing / reward stats.

        Returns dict with keys:
          "skills": List[ComponentPerformanceRecord]
          "tools":  List[ComponentPerformanceRecord]
        """
        records = self._build_stats_records(
            component_name=component_name,
        )

        # Separate skills from tools based on naming conventions
        skill_records = []
        tool_records = []

        for rec in records:
            name = rec.component_name
            if (
                name.startswith("tool_")
                or name
                in (
                    "shell",
                    "python_eval",
                    "read_file",
                    "write_file",
                    "grep",
                    "glob",
                    "http_get",
                )
            ):
                tool_records.append(rec)
            else:
                skill_records.append(rec)

        return {
            "skills": [
                r.model_dump(exclude_none=True) for r in skill_records
            ],
            "tools": [
                r.model_dump(exclude_none=True) for r in tool_records
            ],
        }

    # =====================================================
    # Message Dispatch (overrides base LearnPlugin.handle)
    # =====================================================

    def handle(self, msg: A2EMessage) -> Optional[A2EMessage]:
        """
        Dispatch refinement messages on top of the base learn handlers.

        Adds support for:
          - learn/refinement/plan/req
          - learn/refinement/apply/req
          - learn/refinement/rollback/req
          - learn/refinement/review/req
          - learn/refinement/history/req
        """
        from a2e.caps.base.protocol import A2EError, A2EErrorCode
        from a2e.caps.learn.protocol import (
            MessageType,
            LearnRefinementPlanRequest,
            LearnRefinementPlanResponse,
            LearnRefinementApplyRequest,
            LearnRefinementApplyResponse,
            LearnRefinementRollbackRequest,
            LearnRefinementRollbackResponse,
            LearnRefinementReviewRequest,
            LearnRefinementReviewResponse,
            LearnRefinementHistoryRequest,
            LearnRefinementHistoryResponse,
        )

        req_id = getattr(msg, "id", "")
        t0 = time.monotonic()
        t = getattr(msg, "type", "")

        # ── Refinement Plan ──────────────────────────────────
        if t == MessageType.LEARN_REFINEMENT_PLAN_REQ:
            try:
                plan = self._plan_refinement(
                                component_name=component_name,
                                strategy=strategy,
                            )
                response = LearnRefinementPlanResponse(
                    req_id=req_id,
                    plan_id=plan.get("plan_id", ""),
                    proposals=plan.get("proposals", []),
                    status=plan.get("status", ""),
                )
            except Exception as error:
                response = A2EError(
                    req_id=req_id,
                    code=A2EErrorCode.RUNTIME_ERROR,
                    message=str(error),
                    retryable=False,
                )
            finally:
                self.audit_handle(msg, response, req_id, t0)
                return response

        # ── Refinement Apply ─────────────────────────────────
        if t == MessageType.LEARN_REFINEMENT_APPLY_REQ:
            try:
                result = self.refine(action="apply", proposal=msg.proposal)
                response = LearnRefinementApplyResponse(
                    req_id=req_id,
                    refinement_id=result.get("refinement_id", ""),
                    applied_edits=result.get("applied_edits", 0),
                    failed_edits=result.get("failed_edits", 0),
                    rollback_available=result.get("rollback_available", False),
                    error=result.get("error", ""),
                )
            except Exception as error:
                response = A2EError(
                    req_id=req_id,
                    code=A2EErrorCode.RUNTIME_ERROR,
                    message=str(error),
                    retryable=False,
                )
            finally:
                self.audit_handle(msg, response, req_id, t0)
                return response

        # ── Refinement Rollback ──────────────────────────────
        if t == MessageType.LEARN_REFINEMENT_ROLLBACK_REQ:
            try:
                result = self.refine(action="rollback", refinement_id=msg.refinement_id)
                response = LearnRefinementRollbackResponse(
                    req_id=req_id,
                    refinement_id=result.get("refinement_id", ""),
                    rolled_back=result.get("rolled_back", False),
                    error=result.get("error", ""),
                )
            except Exception as error:
                response = A2EError(
                    req_id=req_id,
                    code=A2EErrorCode.RUNTIME_ERROR,
                    message=str(error),
                    retryable=False,
                )
            finally:
                self.audit_handle(msg, response, req_id, t0)
                return response

        # ── Refinement Review ────────────────────────────────
        if t == MessageType.LEARN_REFINEMENT_REVIEW_REQ:
            try:
                result = self.refine(action="review", proposal=msg.proposal)
                response = LearnRefinementReviewResponse(
                    req_id=req_id,
                    approved=result.get("approved", False),
                    confidence_adjusted=result.get(
                        "confidence_adjusted", 0.0
                    ),
                    reasons=result.get("reasons", []),
                    risk_level=result.get("risk_level", "low"),
                )
            except Exception as error:
                response = A2EError(
                    req_id=req_id,
                    code=A2EErrorCode.RUNTIME_ERROR,
                    message=str(error),
                    retryable=False,
                )
            finally:
                self.audit_handle(msg, response, req_id, t0)
                return response

        # ── Refinement History ───────────────────────────────
        if t == MessageType.LEARN_REFINEMENT_HISTORY_REQ:
            try:
                entries = self.load_history()
                response = LearnRefinementHistoryResponse(
                    req_id=req_id,
                    entries=entries,
                )
            except Exception as error:
                response = A2EError(
                    req_id=req_id,
                    code=A2EErrorCode.RUNTIME_ERROR,
                    message=str(error),
                    retryable=False,
                )
            finally:
                self.audit_handle(msg, response, req_id, t0)
                return response

        # ── Fall through to base handler ─────────────────────
        return super().handle(msg)

    # =====================================================
    # Stats
    # =====================================================

    def _build_stats_records(
        self,
        component_name: str = "",
    ) -> List[ComponentPerformanceRecord]:
        """Build ComponentPerformanceRecord list from internal stats."""
        records = []

        with self._lock:
            for name, stat in self._stats.items():
                if component_name and name != component_name:
                    continue

                calls_total = stat["calls_total"]
                calls_success = stat["calls_success"]
                calls_failed = stat["calls_failed"]
                scores = stat["scores"]
                durations = stat["durations_ms"]

                avg_score = (
                    round(mean(scores), 4) if scores else 0.0
                )
                avg_duration = (
                    round(mean(durations), 2) if durations else 0.0
                )
                p95_duration = (
                    round(
                        sorted(durations)[int(len(durations) * 0.95)]
                        if len(durations) > 1
                        else (durations[0] if durations else 0.0)
                    , 2)
                )

                records.append(
                    ComponentPerformanceRecord(
                        component_name=name,
                        calls_total=calls_total,
                        calls_success=calls_success,
                        calls_failed=calls_failed,
                        avg_duration_ms=avg_duration,
                        avg_score=avg_score,
                        last_called=stat["last_called"],
                        p95_duration_ms=p95_duration,
                    )
                )

        return records

    # =====================================================
    # Public API (for direct use, not just message dispatch)
    # =====================================================

    def plan_refinement(
        self,
        feedbacks: List[Feedback] = None,
        experiences: List[Experience] = None,
        scope: str = "local",
        component_name: str = "",
        strategy: AdaptStrategy = AdaptStrategy.PPO,
    ) -> Dict[str, Any]:
        """
        Generate a refinement plan from feedback and experiences.

        Reuses existing Feedback/Experience primitives to:
          - Identify low-scoring feedback
          - Identify low-reward experiences
          - Propose targeted adjustments
        """
        fb = feedbacks or self._feedbacks
        exp = experiences or self._experiences

        plan_id = uuid.uuid4().hex[:12]
        proposals = []

        # Analyze feedback for low scores
        for fb_item in fb:
            score = float(fb_item.score or 0.0)
            if score >= 0.5:
                continue

            rated_turn = fb_item.rated_turn
            dim = (
                fb_item.dimension.value
                if hasattr(fb_item.dimension, "value")
                else str(fb_item.dimension or "overall")
            )
            skill = (
                rated_turn.version
                if rated_turn and rated_turn.version
                else (rated_turn.model if rated_turn else "")
                or component_name
                or "unknown"
            )

            edits = []

            # Propose prompt adjustment for low response quality
            if dim in ("correctness", "helpfulness", "plan_quality", "overall"):
                edits.append({
                    "target": "prompt",
                    "op": "update",
                    "path": "prompt.template",
                    "old_value": None,
                    "new_value": f"Refine: improve {dim} for {skill}",
                    "reason": f"Low feedback score {score:.2f} on {dim}",
                })

            # Propose threshold adjustment for verifier
            if dim in ("correctness", "overall"):
                edits.append({
                    "target": "verifier",
                    "op": "update",
                    "path": "verifier.threshold",
                    "old_value": None,
                    "new_value": round(0.5 + (score * 0.3), 4),
                    "reason": f"Adjust verifier threshold based on score {score:.2f}",
                })

            # Propose tool weight adjustment
            if dim in ("helpfulness", "overall"):
                edits.append({
                    "target": "router_weight",
                    "op": "update",
                    "path": f"router.weights.{skill}",
                    "old_value": None,
                    "new_value": round(max(0.1, score), 4),
                    "reason": f"Adjust router weight for {skill} based on score {score:.2f}",
                })

            if edits:
                proposals.append({
                    "refinement_id": uuid.uuid4().hex[:12],
                    "scope": scope,
                    "component_name": skill,
                    "feedback_summary": f"Low score {score:.2f} on {dim}",
                    "edits": edits,
                    "confidence": round(min(1.0, max(0.0, 1.0 - score)), 4),
                    "created_at": time.time(),
                    "status": "proposed",
                })

        # Analyze experiences for low rewards
        for exp_item in exp:
            reward = float(exp_item.reward or 0.0)
            if reward >= 0.3:
                continue

            action = exp_item.action or {}
            exp_skill = action.get("component_name", "") or component_name or "unknown"

            edits = []

            # Propose skill routing adjustment
            for s in action.get("skills", []):
                edits.append({
                    "target": "router_weight",
                    "op": "update",
                    "path": f"router.weights.{s}",
                    "old_value": None,
                    "new_value": round(max(0.05, reward), 4),
                    "reason": f"Reduce weight for {s} (reward={reward:.2f})",
                })

            # Propose tool usage adjustment
            for t in action.get("tools", []):
                edits.append({
                    "target": "tool",
                    "op": "update",
                    "path": f"tool_config.{t}.max_calls",
                    "old_value": None,
                    "new_value": 1,
                    "reason": f"Reduce {t} usage (reward={reward:.2f})",
                })

            if edits:
                proposals.append({
                    "refinement_id": uuid.uuid4().hex[:12],
                    "scope": scope,
                    "component_name": exp_skill,
                    "feedback_summary": f"Low reward {reward:.2f} from experience",
                    "edits": edits,
                    "confidence": round(min(1.0, max(0.0, 1.0 - reward)), 4),
                    "created_at": time.time(),
                    "status": "proposed",
                })

        # Deduplicate by (target, path)
        seen = set()
        unique_proposals = []
        for p in proposals:
            key = (
                p["component_name"],
                tuple(
                    (e["target"], e["path"]) for e in p.get("edits", [])
                ),
            )
            if key not in seen:
                seen.add(key)
                unique_proposals.append(p)

        return {
            "plan_id": plan_id,
            "scope": scope,
            "component_name": component_name,
            "proposals": unique_proposals,
            "created_at": time.time(),
            "status": "approved" if unique_proposals else "completed",
        }

    def apply_refinement(
        self,
        proposal: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Apply a refinement proposal atomically with before/after snapshot.

        Reuses existing Feedback/Experience stats and stores the result
        in refinements.jsonl for history tracking.
        """
        current_state = self._get_current_state()
        before_snapshot = copy.deepcopy(current_state)

        edits = proposal.get("edits", [])
        applied = 0
        failed = 0
        error = None

        try:
            for edit in edits:
                valid, msg = self._validate_edit(edit, current_state)
                if not valid:
                    failed += 1
                    continue
                self._apply_edit(edit, current_state)
                applied += 1
        except Exception as e:
            error = str(e)
            failed = len(edits) - applied

        after_snapshot = copy.deepcopy(current_state)

        result = {
            "refinement_id": proposal.get("refinement_id", ""),
            "scope": proposal.get("scope", self._default_scope),
            "applied_edits": applied,
            "failed_edits": failed,
            "before_snapshot": before_snapshot,
            "after_snapshot": after_snapshot,
            "rollback_available": applied > 0,
            "error": error,
            "created_at": time.time(),
        }

        # Save before snapshot for rollback
        rid = proposal.get("refinement_id", "")
        if rid:
            self._rollback_stack[rid] = before_snapshot

        # Record in history
        self._append_refinement_history(result)

        # Update harness state
        self._update_harness_state(current_state)
        self.store.save_state()

        return result

    def rollback_refinement(
        self,
        refinement_id: str,
    ) -> Dict[str, Any]:
        """Public: rollback a previously applied refinement."""
        return self._rollback(refinement_id)

    def review_proposal(
        self,
        proposal: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Auto-review gate for a refinement proposal.

        Checks:
          - Confidence threshold
          - Conflicting edits (same target+path, different new_values)
          - History for similar past refinements (duplicate detection)
        """
        confidence = proposal.get("confidence", 0.0)
        risk_level = "low"
        reasons = []

        # Check confidence threshold
        if confidence < self._confidence_threshold:
            reasons.append(
                f"Confidence {confidence:.2f} below threshold {self._confidence_threshold}"
            )
            risk_level = "high"

        # Check for conflicting edits
        seen_paths = {}
        for edit in proposal.get("edits", []):
            key = (edit.get("target", ""), edit.get("path", ""))
            if key in seen_paths:
                prev = seen_paths[key]
                if prev.get("new_value") != edit.get("new_value"):
                    reasons.append(
                        f"Conflict: {edit.get('target')}:{edit.get('path')} "
                        f"has conflicting values ({prev.get('new_value')} vs {edit.get('new_value')})"
                    )
                    risk_level = "high"
            else:
                seen_paths[key] = edit

        # Check history for duplicate edits
        history = self.store.load_refinements()
        for prev in history:
            for prev_edit in prev.get("edits", []):
                for cur_edit in proposal.get("edits", []):
                    if (
                        prev_edit.get("target") == cur_edit.get("target")
                        and prev_edit.get("path") == cur_edit.get("path")
                        and prev_edit.get("new_value") == cur_edit.get("new_value")
                    ):
                        reasons.append(
                            f"Duplicate edit: {cur_edit.get('target')}:{cur_edit.get('path')} "
                            f"already applied in prior refinement"
                        )
                        risk_level = "medium"

        # Adjust confidence based on risk
        adjusted = confidence
        if risk_level == "high":
            adjusted *= 0.5
        elif risk_level == "medium":
            adjusted *= 0.8

        approved = (
            risk_level != "high"
            and len(proposal.get("edits", [])) > 0
            and adjusted >= self._confidence_threshold
        )

        return {
            "approved": approved,
            "confidence_adjusted": round(adjusted, 4),
            "reasons": reasons,
            "risk_level": risk_level,
        }

    def load_history(self) -> List[Dict[str, Any]]:
        """Public: load refinement history."""
        return self.store.load_refinements()

    def merge_history(self, other_history: List[Dict[str, Any]]) -> int:
        """Public: merge external refinement history."""
        return self.store.merge_refinements(other_history)

    def get_harness_state(self) -> HarnessState:
        """Public: get current harness state snapshot."""
        return self._harness_state

    # =====================================================
    # Internal helpers (refinement logic)
    # =====================================================

    def _plan_refinement(
        self,
        component_name: str = "",
        strategy: AdaptStrategy = AdaptStrategy.PPO,
    ) -> Dict[str, Any]:
        """Internal: generate a refinement plan from feedback and experiences."""
        experiences = self.store.load_experiences()
        feedbacks = self.store.load_feedbacks()

        proposals = []

        # Analyze feedback to identify underperforming components
        if component_name:
            candidates = [c for c in experiences if c.get("action", {}).get("component_name") == component_name]
        else:
            candidates = experiences

        if not candidates and not feedbacks:
            return {"plan_id": "", "proposals": [], "status": "empty"}

        # Group by component and compute scores
        scores = {}
        for exp in candidates:
            cn = exp.get("action", {}).get("component_name", "")
            if cn not in scores:
                scores[cn] = {"rewards": [], "count": 0}
            scores[cn]["rewards"].append(exp.get("reward", 0.0))
            scores[cn]["count"] += 1

        for fb in feedbacks:
            for rated in fb.get("rated_turns", []) if isinstance(fb.get("rated_turns"), list) else [fb.get("rated_turn")]:
                if rated is None:
                    continue
                cn = rated.get("component_name", "")
                if cn not in scores:
                    scores[cn] = {"rewards": [], "count": 0}
                scores[cn]["rewards"].append(fb.get("score", 0.0))
                scores[cn]["count"] += 1

        # Generate proposals based on strategy
        for cn, data in scores.items():
            avg_reward = sum(data["rewards"]) / max(data["count"], 1)
            if avg_reward < 0.5 and data["count"] >= self._min_experiences:
                proposals.append({
                    "target": "router_weight",
                    "op": "update",
                    "path": f"router.weights.{cn}",
                    "old_value": None,
                    "new_value": round(min(1.0, avg_reward * 2), 4),
                    "component_name": cn,
                    "strategy": strategy.value,
                    "reason": f"Low avg reward {avg_reward:.2f} over {data['count']} calls",
                })

        plan_id = f"plan-{hash(str(proposals)) & 0xffffffff:08x}"
        return {
            "plan_id": plan_id,
            "proposals": proposals,
            "status": "ready" if proposals else "empty",
        }

    def _review_proposal(
        self,
        proposal: Dict[str, Any],
        history: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Internal: auto-review gate for a proposal."""
        return self.review_proposal(proposal)

    def _validate_edit(
        self,
        edit: Dict[str, Any],
        current_state: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """Validate a single edit before applying."""
        valid_targets = {
            "prompt", "tool", "router_weight", "verifier", "router"
        }
        valid_ops = {"replace", "insert", "delete", "update"}

        target = edit.get("target", "")
        op = edit.get("op", "")
        path = edit.get("path", "")

        if target not in valid_targets:
            return False, f"Unknown target: {target}"

        if op not in valid_ops:
            return False, f"Unknown op: {op}"

        if not path:
            return False, "Empty path"

        if op in ("replace", "insert", "update") and edit.get("new_value") is None:
            return False, f"new_value required for op={op}"

        # Block dangerous paths
        dangerous_prefixes = ("__", "os.", "sys.", "subprocess")
        for prefix in dangerous_prefixes:
            if path.startswith(prefix):
                return False, f"Path '{path}' is not allowed"

        return True, ""

    def _validate_proposal(
        self,
        proposal: Dict[str, Any],
        current_state: Dict[str, Any],
    ) -> Tuple[bool, List[str]]:
        """Validate all edits in a proposal."""
        errors = []
        for edit in proposal.get("edits", []):
            valid, msg = self._validate_edit(edit, current_state)
            if not valid:
                errors.append(f"Edit[{edit.get('target')}:{edit.get('path')}]: {msg}")
        return len(errors) == 0, errors

    def _apply_edit(
        self,
        edit: Dict[str, Any],
        state: Dict[str, Any],
    ) -> None:
        """Apply a single edit to the state dict."""
        parts = edit.get("path", "").split(".")
        obj = state
        for part in parts[:-1]:
            if part not in obj or not isinstance(obj[part], dict):
                obj[part] = {}
            obj = obj[part]

        key = parts[-1] if parts else edit.get("path", "")
        op = edit.get("op", "replace")
        new_value = edit.get("new_value")

        if op == "replace":
            obj[key] = new_value
        elif op == "insert":
            if key not in obj:
                obj[key] = new_value
        elif op == "delete":
            obj.pop(key, None)
        elif op == "update":
            if key in obj and isinstance(obj[key], (int, float)) and isinstance(new_value, (int, float)):
                obj[key] = new_value
            else:
                obj[key] = new_value

    def _apply_edits(
        self,
        edits: List[Dict[str, Any]],
        state: Dict[str, Any],
    ) -> Tuple[int, int]:
        """Apply multiple edits, returning (applied_count, failed_count)."""
        applied = 0
        failed = 0
        for edit in edits:
            valid, _ = self._validate_edit(edit, state)
            if not valid:
                failed += 1
                continue
            try:
                self._apply_edit(edit, state)
                applied += 1
            except Exception:
                failed += 1
        return applied, failed

    def _append_refinement_history(self, record: Dict[str, Any]) -> None:
        """Append a refinement result to history."""
        record.setdefault("ts", time.time())
        self.store.append_refinement(record)

    def _get_current_state(self) -> Dict[str, Any]:
        """Capture current state for snapshot/rollback."""
        return {
            "policy_name": self._harness_state.policy_name,
            "policy_version": self._harness_state.policy_version,
            "checkpoint_uri": self._harness_state.checkpoint_uri,
            "stats": {
                name: {
                    "calls_total": s["calls_total"],
                    "calls_success": s["calls_success"],
                    "calls_failed": s["calls_failed"],
                    "reward_total": s["reward_total"],
                    "last_called": s["last_called"],
                }
                for name, s in self._stats.items()
            },
            "rollouts": self._harness_state.rollouts,
            "scope": self._harness_state.scope,
        }

    def _update_harness_state(self, current_state: Dict[str, Any]) -> None:
        """Update harness state from current state."""
        self._harness_state.stats = current_state.get("stats", {})
        self._harness_state.scope = current_state.get("scope", self._default_scope)
        self._harness_state.updated_at = time.time()