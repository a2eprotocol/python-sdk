import pdb
from typing import Optional

from a2e.core.client import A2EClient
from a2e.caps.learn import (
    LearnFeedbackRequest,
    LearnFeedbackResponse,
    LearnExperienceRequest,
    LearnExperienceResponse,
    LearnAdaptRequest,
    LearnAdaptResponse,
    LearnStatsRequest,
    LearnStatsResponse,
    Experience,
    Feedback,
    FeedbackPolarity,
    FeedbackDimension,
    FeedbackSource,
    RatedTurn,
    SkillPerformanceRecord,
    LEARN_TYPE_MAP
)


class LearnAPI:
    def __init__(self, client: A2EClient):
        self._c = client
        self._c.update_msg_types(LEARN_TYPE_MAP)

    def feedback(
        self,

        # -------------------------------------------------
        # Core Signal
        # -------------------------------------------------

        polarity: FeedbackPolarity,
        score: float = 0.0,
        dimension: FeedbackDimension = (
            FeedbackDimension.HELPFULNESS
        ),
        confidence: float = 1.0,

        # -------------------------------------------------
        # Rated Turn
        # -------------------------------------------------
        prompt: str = "",
        response: str = "",
        model: str = "",
        environment: Optional[dict] = None,
        version: Optional[str] = None,

        # -------------------------------------------------
        # Correlation
        # -------------------------------------------------
        correlation_id: str = "",
        session_id: str = "",

        # -------------------------------------------------
        # Human / Harness Feedback
        # -------------------------------------------------
        comment: str = "",
        correction: str = "",
        correction_span: Optional[
            tuple[int, int]
        ] = None,

        # -------------------------------------------------
        # Provenance
        # -------------------------------------------------
        source: FeedbackSource = (
            FeedbackSource.HUMAN
        ),

        annotator_id: str = "",

        # -------------------------------------------------
        # Runtime
        # -------------------------------------------------
        timeout: int = 10,

    ) -> LearnFeedbackResponse:

        """
        Submit structured feedback signal.

        Supports:
          - human feedback
          - env reward signals
          - verifier critique
          - corrective preference learning
          - dimension-specific reward modeling
        """

        # =================================================
        # Build Rated Turn
        # =================================================
        rated_turn = None

        if prompt or response:
            rated_turn = RatedTurn(
                prompt=prompt,
                response=response,
                model=model,
                environment=environment,
                version=version,
            )

        # =================================================
        # Build Feedback
        # =================================================

        fb = Feedback(

            # ---------------------------------------------
            # Correlation
            # ---------------------------------------------

            correlation_id=correlation_id,

            session_id=session_id,

            # ---------------------------------------------
            # Rated Artifact
            # ---------------------------------------------

            rated_turn=rated_turn,

            # ---------------------------------------------
            # Signal
            # ---------------------------------------------

            polarity=polarity,

            score=score,

            dimension=dimension,

            confidence=confidence,

            # ---------------------------------------------
            # Human / Corrective
            # ---------------------------------------------

            comment=comment,

            correction=correction,

            correction_span=correction_span,

            # ---------------------------------------------
            # Provenance
            # ---------------------------------------------

            source=source,

            annotator_id=annotator_id,
        )

        # =================================================
        # RPC Request
        # =================================================
        req = LearnFeedbackRequest(
            feedbacks=[fb]
        )

        # =================================================
        # Execute RPC
        # =================================================

        resp = self._c.rpc(
            req,
            timeout=timeout,
        )

        if not isinstance(
            resp,
            LearnFeedbackResponse,
        ):

            raise ConnectionError(
                "Unexpected feedback response: "
                f"{type(resp)}"
            )

        return resp

    def experience(
        self,
        experiences: list[Experience] | list[dict],
        timeout: int = 10,
    ) -> int:
        raw = [e if isinstance(e, dict) else e.__dict__ for e in experiences]
        req = LearnExperienceRequest(experiences=raw)
        resp = self._c.rpc(req, timeout=timeout)
        if not isinstance(resp, LearnExperienceResponse):
            raise ConnectionError(f"Unexpected experience response: {type(resp)}")
        return resp.stored

    def adapt(self, skill_name: str = "", strategy: str = "ucb1",
              timeout: int = 10) -> list[SkillPerformanceRecord]:
        req = LearnAdaptRequest(skill_name=skill_name, strategy=strategy)
        resp = self._c.rpc(req, timeout=timeout)
        if not isinstance(resp, LearnAdaptResponse):
            raise ConnectionError(f"Unexpected adapt response: {type(resp)}")
        return [SkillPerformanceRecord(**r) for r in resp.updated]

    def stats(
        self,
        skill_name: str = "",
        tool_name: str = "",
        timeout: int = 10
    ) -> tuple[list[SkillPerformanceRecord], list[SkillPerformanceRecord]]:
        req = LearnStatsRequest(skill_name=skill_name, tool_name=tool_name)
        resp = self._c.rpc(req, timeout=timeout)
        if not isinstance(resp, LearnStatsResponse):
            raise ConnectionError(f"Unexpected stats response: {type(resp)}")
        skills = [SkillPerformanceRecord(**r) for r in resp.skills]
        tools = [SkillPerformanceRecord(**r) for r in resp.tools]
        return skills, tools

    def reward(self, skill_name: str, value: float, correlation_id: str = ""):
        """Convenience: send a scalar reward signal as positive/negative feedback."""
        polarity = "positive" if value >= 0 else "negative"
        return self.feedback(polarity=polarity, score=value,
                             skill_name=skill_name,
                             correlation_id=correlation_id,
                             source="env")
