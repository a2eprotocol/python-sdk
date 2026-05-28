from __future__ import annotations
import pdb
import threading
import time
import uuid
from collections import defaultdict
from statistics import mean
from typing import Dict, List

from a2e.caps.learn.plugin import LearnPlugin

from a2e.caps.learn.protocol import (
    Feedback,
    Experience,
    SkillPerformanceRecord,
)


class Learn(LearnPlugin):

    """
    Server-side learning plugin.

    Responsibilities:
      - ingest feedback
      - store trajectories / experiences
      - aggregate rewards
      - maintain routing stats
      - launch adaptation jobs
      - expose runtime performance metrics

    This plugin lives inside the A2E Host runtime.
    """

    name = "learn"

    priority = 5

    # =====================================================
    # Init
    # =====================================================

    def __init__(self, host_instance, config):

        super().setup(host_instance, config)

        self.logger = host_instance.logger

        # ---------------------------------------------
        # Raw Stores
        # ---------------------------------------------

        self._feedbacks: List[Feedback] = []

        self._experiences: List[Experience] = []

        # ---------------------------------------------
        # Aggregated Performance Stats
        # ---------------------------------------------

        self._stats = defaultdict(
            lambda: {
                "calls_total": 0,
                "success_total": 0,
                "scores": [],
                "avg_latency_ms": 0.0,
                "reward_total": 0.0,
            }
        )

        # ---------------------------------------------
        # Rollouts / Policy Metadata
        # ---------------------------------------------

        self._rollouts = {}

        self._active_policy = {
            "policy_name": "default",
            "version": "v1",
            "checkpoint_uri": None,
        }

        # ---------------------------------------------
        # Adapt Config
        # ---------------------------------------------

        self._adapt_every = getattr(
            config,
            "adapt_every",
            100,
        )

        self._min_experiences = getattr(
            config,
            "min_experiences",
            32,
        )

        self._lock = threading.Lock()

    # =====================================================
    # Feedback Recording
    # =====================================================

    def _record_feedback(
        self,
        feedbacks: List[Feedback],
    ):

        """
        Persist reward / feedback signals.

        Feedback is lightweight:
          - verifier outputs
          - env rewards
          - user corrections
          - harness scoring
          - latency penalties
        """

        if not feedbacks:
            return {
                "count": 0,
                "scores_by_dimension": {},
            }

        dimension_scores = defaultdict(list)

        with self._lock:

            for fb in feedbacks:

                self._feedbacks.append(fb)
                
                score = float(fb.score or 0.0)

                skill_name = (
                    getattr(fb, "skill_name", None)
                    or getattr(fb, "tool_name", None)
                    or "unknown"
                )

                stat = self._stats[skill_name]

                stat["scores"].append(score)

                stat["reward_total"] += score

                if score > 0:
                    stat["success_total"] += 1

                dimension = getattr(
                    fb,
                    "dimension",
                    "overall",
                )

                dimension_scores[
                    dimension
                ].append(score)

        scores_by_dimension = {
            k: round(mean(v), 4)
            for k, v in dimension_scores.items()
        }

        self.logger.info(
            "[learn.feedback] recorded=%s",
            len(feedbacks),
        )

        return len(feedbacks), scores_by_dimension.get("overall", 0.0)

    # =====================================================
    # Experience Storage
    # =====================================================

    def _store_experiences(
        self,
        experiences: List[Experience],
    ):

        """
        Store RL transitions / trajectories.

        Experiences are heavier than feedback:
          - state
          - action
          - reward
          - next_state
          - done
        """

        if not experiences:
            return 0

        with self._lock:

            for exp in experiences:

                self._experiences.append(exp)
                
                action = exp.action or {}

                # -----------------------------
                # Skills
                # -----------------------------

                for skill_name in action.get(
                    "skills",
                    [],
                ):

                    stat = self._stats[
                        skill_name
                    ]

                    stat["calls_total"] += 1

                    stat["reward_total"] += (
                        exp.reward or 0.0
                    )

                # -----------------------------
                # Tools
                # -----------------------------

                for tool_name in action.get(
                    "tools",
                    [],
                ):

                    stat = self._stats[
                        tool_name
                    ]

                    stat["calls_total"] += 1

                    stat["reward_total"] += (
                        exp.reward or 0.0
                    )

        self.logger.info(
            "[learn.experience] stored=%s",
            len(experiences),
        )

        # ---------------------------------------------
        # Trigger Adapt
        # ---------------------------------------------

        if (
            len(self._experiences)
            % self._adapt_every
            == 0
        ):
            try:
                self._adapt(
                    skill_name=None,
                    strategy="ppo",
                )
            except Exception:
                self.logger.exception(
                    "[learn.adapt] failed"
                )

        return len(experiences)

    # =====================================================
    # Adaptation
    # =====================================================

    def _adapt(
        self,
        skill_name=None,
        strategy="ppo",
    ) -> List[SkillPerformanceRecord]:

        """
        Trigger on-policy adaptation.

        Real implementations may:
          - launch PPO
          - train LoRA
          - update router
          - retrain verifier
          - optimize prompts
          - tune planning policy
        """

        with self._lock:

            if (
                len(self._experiences)
                < self._min_experiences
            ):

                self.logger.info(
                    "[learn.adapt] skipped "
                    "(not enough experiences)"
                )

                return []

            # -----------------------------------------
            # Build Rollout
            # -----------------------------------------

            rollout_id = uuid.uuid4().hex

            recent = self._experiences[
                -self._min_experiences:
            ]

            reward_mean = mean([
                float(e.reward or 0.0)
                for e in recent
            ])

            self._rollouts[rollout_id] = {
                "rollout_id": rollout_id,
                "strategy": strategy,
                "reward_mean": reward_mean,
                "size": len(recent),
                "created_at": time.time(),
            }

            self.logger.info(
                "[learn.adapt] rollout=%s "
                "strategy=%s reward=%.4f",
                rollout_id,
                strategy,
                reward_mean,
            )

            # -----------------------------------------
            # Simulated PPO Train
            # -----------------------------------------

            current_version = (
                self._active_policy[
                    "version"
                ]
            )

            next_version = (
                f"v{int(time.time())}"
            )

            checkpoint_uri = (
                f"s3://a2e/checkpoints/"
                f"{next_version}"
            )

            # -----------------------------------------
            # Activate Policy
            # -----------------------------------------

            self._active_policy = {
                "policy_name": (
                    "a2e-react-policy"
                ),
                "version": next_version,
                "checkpoint_uri": (
                    checkpoint_uri
                ),
            }

            self.logger.info(
                "[learn.adapt] activated "
                "%s",
                next_version,
            )

            return self._get_stats(
                skill_name=skill_name,
                strategy=strategy,
            )

    # =====================================================
    # Stats
    # =====================================================

    def _get_stats(
        self,
        skill_name=None,
        strategy=None,
    ) -> List[SkillPerformanceRecord]:

        """
        Return routing / reward stats.

        Used by:
          - planners
          - harness
          - routing systems
          - dashboards
        """

        records = []

        with self._lock:

            for name, stat in (
                self._stats.items()
            ):

                if (
                    skill_name
                    and name != skill_name
                ):
                    continue

                calls_total = stat[
                    "calls_total"
                ]

                success_total = stat[
                    "success_total"
                ]

                avg_score = (
                    mean(stat["scores"])
                    if stat["scores"]
                    else 0.0
                )

                success_rate = (
                    success_total
                    / calls_total
                    if calls_total > 0
                    else 0.0
                )

                records.append(
                    SkillPerformanceRecord(
                        skill_name=name,

                        calls_total=(
                            calls_total
                        ),

                        success_total=(
                            success_total
                        ),

                        success_rate=round(
                            success_rate,
                            4,
                        ),

                        avg_score=round(
                            avg_score,
                            4,
                        ),

                        metadata={
                            "reward_total": (
                                round(
                                    stat[
                                        "reward_total"
                                    ],
                                    4,
                                )
                            ),

                            "policy": (
                                self._active_policy
                            ),
                        },
                    )
                )

        return records
