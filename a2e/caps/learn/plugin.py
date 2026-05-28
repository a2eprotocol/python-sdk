# ---------------------------------------------------------------------------
# BASE Learn PLUGIN
# ---------------------------------------------------------------------------
import pdb
import time
from pydantic import BaseModel
from typing import Dict, Type, Optional, List

from a2e.caps.base import (
    A2EMessage,
    A2EError,
    A2EErrorCode
)
from a2e.caps.learn.protocol import (
    LEARN_TYPE_MAP,
    LearnFeedbackResponse,
    LearnExperienceResponse,
    LearnAdaptResponse,
    LearnStatsResponse,
    MessageType,
    Feedback,
    Experience,
    SkillPerformanceRecord
)
from a2e.core.plugins import (
    A2EPlugin
)


class LearnPlugin(A2EPlugin):
    name = "learn"
    priority = 5

    def __init__(self, host_instance, config):
        super().setup(host_instance, config)

    def _record_feedback(self, feedbacks: List[Feedback]):
        """
        Persist feedback records.

        Returns:
            count:              number successfully recorded
            scores_by_dimension: e.g.
                {"helpfulness": 0.7, "correctness": 0.4}
                derived from the feedback batch, used in response
        """
        return NotImplementedError

    def _store_experiences(self, experiences: List[Experience]):
        """Persist experience records. Returns count stored."""
        return NotImplementedError

    def _adapt(self, skill_name, strategy) -> List[SkillPerformanceRecord]:
        """Trigger adaptation for a skill within an agent context."""
        return NotImplementedError

    def _get_stats(self, skill_name, strategy) -> List[SkillPerformanceRecord]:
        """
        Fetch performance stats.

        Returns dict with keys:
            "skills": List[SkillPerformanceRecord]
            "tools":  List[...]
        """
        return NotImplementedError

    # ----------------------------------------------------
    # Protocol Messages
    # -----------------------------------------------------
    def supported_messages(self) -> Dict[str, Type[BaseModel]]:
        return LEARN_TYPE_MAP

    def handle(self, msg: A2EMessage) -> Optional[A2EMessage]:
        response = None
        req_id = msg.id
        t0 = time.monotonic()
        t = msg.type

        # ---------------------------------------------
        # FEEDBACK
        # ---------------------------------------------
        if t == MessageType.LEARN_FEEDBACK_REQ:
            try:
                count, score = self._record_feedback(
                    msg.feedbacks
                )

                response = LearnFeedbackResponse(
                    req_id=req_id,
                    recorded=count,
                    new_score=score,
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

        # ---------------------------------------------
        # EXPERIENCE
        # ---------------------------------------------
        if t == MessageType.LEARN_EXPERIENCE_REQ:
            try:
                stored = self._store_experiences(
                    msg.experiences
                )

                response = LearnExperienceResponse(
                    req_id=req_id,
                    stored=stored,
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

        # ---------------------------------------------
        # ADAPT
        # ---------------------------------------------
        if t == MessageType.LEARN_ADAPT_REQ:
            try:
                updated = self._adapt(
                    msg.skill_name,
                    msg.strategy,
                )

                response = LearnAdaptResponse(
                    req_id=req_id,
                    updated=updated,
                    message=(
                        f"Adapted "
                        f"{len(updated)} skills "
                        f"using {msg.strategy}"
                    ),
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

        # ---------------------------------------------
        # STATS
        # ---------------------------------------------
        if t == MessageType.LEARN_STATS_REQ:
            try:
                stats = self._get_stats(
                    msg.skill_name,
                    msg.tool_name,
                )

                response = LearnStatsResponse(
                    req_id=req_id,
                    skills=stats.get(
                        "skills",
                        [],
                    ),
                    tools=stats.get(
                        "tools",
                        [],
                    ),
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

        # ---------------------------------------------
        # Unsupported Message
        # ---------------------------------------------
        response = A2EError(
            req_id=req_id,
            code=A2EErrorCode.INVALID_MESSAGE,
            message=f"[learn] Unsupported message: {t}",
            retryable=False,
        )

        self.audit_handle(msg, response, req_id, t0)
        return response
