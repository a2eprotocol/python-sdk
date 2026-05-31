# ─────────────────────────────────────────────────────────────
# SkillPlugin
# ─────────────────────────────────────────────────────────────
import time
import logging
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel

from a2e.caps.base import (
    A2EMessage,
    A2EErrorCode,
    A2EError
)

from a2e.core.plugins import A2EPlugin

from a2e.caps.skills.protocol import (
    SkillDiscoverRequest,
    SkillDiscoverResponse,
    SkillCallRequest,
    SkillCallResponse,
    SkillEvent,
    SkillDefinition,
    SkillErrorCode,
    SkillResult,
    SKILL_TYPE_MAP
)


class SkillPlugin(A2EPlugin):
    """
    Generic Skill Plugin.

    Responsibilities:
      • Discover skills (SkillDefinition only)
      • Execute skills (SkillCallRequest → SkillCallResponse)

    This plugin is intentionally generic:
      - Works with any skill registry
      - Can wrap external skill systems
      - Does NOT assume specific execution model
    """
    def __init__(
        self,
        host_instance: Any,
        config: dict
    ):
        super().setup(host_instance, config)
        self.logger = logging.getLogger(__name__)

        self._current_req_id: Optional[str] = None

    # ─────────────────────────────────────────────
    # ABSTRACT METHODS (child must implement)
    # ─────────────────────────────────────────────
    def _list_skills(self) -> List[SkillDefinition]:
        raise NotImplementedError

    def _execute_skill(
        self,
        name: str,
        arguments: Dict[str, Any],
        context: Dict[str, Any],
    ) -> SkillResult:
        raise NotImplementedError

    # ─────────────────────────────────────────────
    # DISCOVER
    # ─────────────────────────────────────────────
    def discover(self, msg: SkillDiscoverRequest) -> List[SkillDefinition]:
        skills = self._list_skills()

        results = []
        for s in skills:
            if msg.filter_tags and not set(msg.filter_tags).intersection(set(s.tags or [])):
                continue

            if msg.filter_categories and s.category not in msg.filter_categories:
                continue

            results.append(s)

        return results

    # ─────────────────────────────────────────────
    # EXECUTION (with streaming aggregation)
    # ─────────────────────────────────────────────
    def call(self, msg: SkillCallRequest) -> SkillCallResponse:
        response = None
        req_id = msg.id
        t0 = time.monotonic()
        events: List[SkillEvent] = []
        seq = 0

        def emit_event(kind: str, data: dict):
            nonlocal seq

            evt = SkillEvent(
                req_id=msg.id,
                kind=kind,
                data=data,
                seq=seq,
            )
            seq += 1

            # stream to client
            self.emit_event(evt)

            # aggregate
            events.append(evt)

        try:
            result = self._execute_skill(
                name=msg.name,
                arguments=msg.arguments,
                context={
                    "emit_event": emit_event,
                    "llm_override": msg.llm_override,
                    "metadata": msg.metadata,
                    "streaming": msg.streaming
                },
            )

            response = SkillCallResponse(
                req_id=msg.id,
                name=msg.name,
                status=0,
                data=result,
            )
        except Exception as e:
            self.logger.exception(f"[skill] failed: {msg.name}")
            response = A2EError(
                req_id=msg.id,
                code=SkillErrorCode.SKILL_ERROR,
                message=str(e),
                retryable=False,
            )
        finally:
            self.audit_handle(msg, response, req_id, t0)
            return response

    # ---------------------------------------------------------
    # Supported Messages
    # ---------------------------------------------------------
    def supported_messages(self) -> Dict[str, Type[BaseModel]]:
        return SKILL_TYPE_MAP

    # ─────────────────────────────────────────────
    # HANDLE
    # ─────────────────────────────────────────────
    def handle(self, msg: A2EMessage) -> Optional[A2EMessage]:
        response = None
        req_id = msg.id
        t0 = time.monotonic()

        if isinstance(msg, SkillDiscoverRequest):
            try:
                skills = self.discover(msg)
                response = SkillDiscoverResponse(
                    req_id=req_id,
                    skills=skills,
                )
            except Exception as error:
                req_id = msg.get("id", "")
                response = A2EError(**{
                    "req_id": req_id,
                    "code": SkillErrorCode.RUNTIME_ERROR,
                    "message": str(error),
                    "retryable": False
                })
            finally:
                self.audit_handle(msg, response, req_id, t0)
                return response

        # Skill Call
        if isinstance(msg, SkillCallRequest):
            return self.call(msg)

        # Return invalid message
        response = A2EError(**{
            "req_id": req_id,
            "code": A2EErrorCode.INVALID_MESSAGE,
            "message": f"Invalid message: {msg.type}",
            "retryable": False
        })
        self.audit_handle(msg, response, req_id, t0)
        return None
