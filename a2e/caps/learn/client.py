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
    Experience,
    Feedback,
    FeedbackPolarity,
    FeedbackDimension,
    FeedbackSource,
    RatedTurn,
    ComponentPerformanceRecord,
    AdaptStrategy,
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

    def adapt(self, component_name: str = "", strategy: AdaptStrategy = AdaptStrategy.PPO,
              timeout: int = 10) -> list[ComponentPerformanceRecord]:
        """Fire-and-forget: server handles plan → review → apply → stats."""
        req = LearnAdaptRequest(component_name=component_name, strategy=strategy)
        resp = self._c.rpc(req, timeout=timeout)
        if not isinstance(resp, LearnAdaptResponse):
            raise ConnectionError(f"Unexpected adapt response: {type(resp)}")
        return [ComponentPerformanceRecord(**r) for r in resp.updated]

    def refine(
        self,
        component_name: str = "",
        action: str = "plan",
        proposal: Optional[dict] = None,
        refinement_id: str = "",
        scope: str = "local",
        strategy: AdaptStrategy = AdaptStrategy.PPO,
        timeout: int = 10,
    ) -> dict:
        """
        Unified refinement interface — one method, five modes.

        actions:
          plan     — generate proposals from feedback
          review   — gate a proposal (confidence, conflicts, history)
          apply    — apply a proposal atomically
          rollback — undo a previous apply
          history  — load refinement history
        """
        if action == "plan":
            req = LearnRefinementPlanRequest(
                component_name=component_name, scope=scope,
            )
            resp = self._c.rpc(req, timeout=timeout)
            if not isinstance(resp, LearnRefinementPlanResponse):
                raise ConnectionError(
                    f"Unexpected refinement plan response: {type(resp)}"
                )
            return {
                "plan_id": resp.plan_id,
                "proposals": resp.proposals,
                "status": resp.status,
            }

        elif action == "review":
            if proposal is None:
                raise ValueError("review requires a proposal")
            req = LearnRefinementReviewRequest(proposal=proposal)
            resp = self._c.rpc(req, timeout=timeout)
            if not isinstance(resp, LearnRefinementReviewResponse):
                raise ConnectionError(
                    f"Unexpected refinement review response: {type(resp)}"
                )
            return {
                "approved": resp.approved,
                "confidence_adjusted": resp.confidence_adjusted,
                "reasons": resp.reasons,
                "risk_level": resp.risk_level,
            }

        elif action == "apply":
            if proposal is None:
                raise ValueError("apply requires a proposal")
            req = LearnRefinementApplyRequest(proposal=proposal)
            resp = self._c.rpc(req, timeout=timeout)
            if not isinstance(resp, LearnRefinementApplyResponse):
                raise ConnectionError(
                    f"Unexpected refinement apply response: {type(resp)}"
                )
            return {
                "refinement_id": resp.refinement_id,
                "applied_edits": resp.applied_edits,
                "failed_edits": resp.failed_edits,
                "rollback_available": resp.rollback_available,
                "error": resp.error,
            }

        elif action == "rollback":
            if not refinement_id:
                raise ValueError("rollback requires a refinement_id")
            req = LearnRefinementRollbackRequest(refinement_id=refinement_id)
            resp = self._c.rpc(req, timeout=timeout)
            if not isinstance(resp, LearnRefinementRollbackResponse):
                raise ConnectionError(
                    f"Unexpected refinement rollback response: {type(resp)}"
                )
            return {
                "refinement_id": resp.refinement_id,
                "rolled_back": resp.rolled_back,
                "error": resp.error,
            }

        elif action == "history":
            req = LearnRefinementHistoryRequest()
            resp = self._c.rpc(req, timeout=timeout)
            if not isinstance(resp, LearnRefinementHistoryResponse):
                raise ConnectionError(
                    f"Unexpected refinement history response: {type(resp)}"
                )
            return {"entries": resp.entries}

        else:
            raise ValueError(
                f"Unknown refine action: {action!r}. "
                f"Valid actions: plan, review, apply, rollback, history"
            )

    def stats(
        self,
        component_name: str = "",
        timeout: int = 10
    ) -> list[ComponentPerformanceRecord]:
        req = LearnStatsRequest(component_name=component_name)
        resp = self._c.rpc(req, timeout=timeout)
        if not isinstance(resp, LearnStatsResponse):
            raise ConnectionError(f"Unexpected stats response: {type(resp)}")
        return [ComponentPerformanceRecord(**r) for r in resp.components]

    def reward(self, component_name: str, value: float, correlation_id: str = ""):
        """Convenience: send a scalar reward signal as positive/negative feedback."""
        polarity = "positive" if value >= 0 else "negative"
        return self.feedback(polarity=polarity, score=value,
                             correlation_id=correlation_id,
                             source="env")
