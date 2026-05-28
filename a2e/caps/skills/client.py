import pdb
import uuid
from typing import Callable, Any, Dict

from a2e.core.client import A2EClient
from a2e.caps.base.protocol import A2EError
from a2e.caps.skills.protocol import (
    SkillDiscoverRequest,
    SkillDiscoverResponse,
    SkillCallRequest,
    SkillCallResponse,
    SkillDefinition,
    SkillEvent,
    SkillResult,
    SKILL_TYPE_MAP
)


EventCallback = Callable[[SkillEvent], None]


class SkillAPI:
    def __init__(self, client: A2EClient):
        self._c = client
        self._c.update_msg_types(SKILL_TYPE_MAP)

    # ─────────────────────────────
    # DISCOVER SKILLS
    # ─────────────────────────────
    def discover(
        self,
        tags=None,
        categories=None,
        timeout: int = 10,
    ) -> list[SkillDefinition]:
        req = SkillDiscoverRequest(
            id=uuid.uuid4().hex,
            filter_tags=tags or [],
            filter_categories=categories or []
        )

        resp = self._c.rpc(req, timeout=timeout)

        if not isinstance(resp, SkillDiscoverResponse):
            raise ConnectionError(
                f"Unexpected skill discover response: {type(resp)}"
            )

        return [
            SkillDefinition(**s)
            for s in resp.skills
        ]

    # ─────────────────────────────
    # CALL SKILL
    # ─────────────────────────────
    def call(
        self,
        name: str,
        arguments: Dict[str, Any],
        streaming: bool = True,
        on_event: EventCallback = None,
        timeout: int = 60,
    ):
        req = SkillCallRequest(
            id=uuid.uuid4().hex,
            name=name,
            arguments=arguments,
            streaming=streaming
        )

        resp = self._c.rpc(req, timeout=timeout + 5, event_callback=on_event)

        if isinstance(resp, A2EError):
            return SkillResult(
                success=False,
                name=name,
                data=None,
                duration_ms=0,
                error=resp.message,
                error_code=resp.code,
                events=[]
            )

        if not isinstance(resp, SkillCallResponse):
            raise ConnectionError(f"Unexpected tool response: {type(resp)}")

        return resp.data
