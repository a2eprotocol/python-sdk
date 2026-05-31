"""Tests for SkillPlugin — skill execution plugin."""

import json
import pytest
from unittest.mock import MagicMock, patch
from typing import List

from a2e.caps.skills.plugin import SkillPlugin
from a2e.caps.skills.protocol import (
    SkillDiscoverRequest,
    SkillDiscoverResponse,
    SkillCallRequest,
    SkillCallResponse,
    SkillEvent,
    SkillDefinition,
    SkillErrorCode,
    SkillResult,
    MessageType,
)
from a2e.caps.base.protocol import (
    A2EError,
    A2EErrorCode,
    A2EMessage,
    A2EEvent,
)


# ── Helpers ─────────────────────────────────────────────────────

class MockHost:
    def __init__(self):
        self.sent = []

    def _send(self, msg):
        self.sent.append(msg)


class EchoSkill(SkillPlugin):
    """A skill that echoes the input arguments back."""

    def _list_skills(self) -> List[SkillDefinition]:
        return [
            SkillDefinition(
                name="echo_skill",
                version="1.0",
                description="Echo input back",
                triggers=["echo"],
                status="Published",
                source="test",
                when_to_use="When user wants to echo",
                argument_hint="any JSON",
            )
        ]

    def _execute_skill(self, name, arguments, context):
        events = []
        if context.get("emit_event"):
            context["emit_event"]("progress", {"pct": 100, "message": "done"})
        return SkillResult(
            success=True,
            data={"echo": arguments},
            duration_ms=10,
        )


class FailingSkill(SkillPlugin):
    """A skill that always fails."""

    def _list_skills(self) -> List[SkillDefinition]:
        return []

    def _execute_skill(self, name, arguments, context):
        raise RuntimeError("skill execution failed")


@pytest.fixture
def echo_skill():
    host = MockHost()
    return EchoSkill(host, {"type": "skills", "priority": 0, "exclusive": False})


@pytest.fixture
def failing_skill():
    host = MockHost()
    return FailingSkill(host, {"type": "skills", "priority": 0, "exclusive": False})


# ── Tests ───────────────────────────────────────────────────────

class TestSkillPluginInit:
    def test_current_req_id_none(self, echo_skill):
        assert echo_skill._current_req_id is None

    def test_supported_messages(self, echo_skill):
        msgs = echo_skill.supported_messages()
        assert MessageType.SKILL_DISCOVER_REQ in msgs
        assert MessageType.SKILL_CALL_REQ in msgs


class TestDiscover:
    def test_discover_returns_definitions(self, echo_skill):
        req = SkillDiscoverRequest()
        resp = echo_skill.handle(req)
        assert isinstance(resp, SkillDiscoverResponse)
        assert len(resp.skills) == 1
        assert resp.skills[0].name == "echo_skill"

    def test_discover_with_tag_filter(self, echo_skill):
        """Tags filter should exclude skills that don't match."""
        req = SkillDiscoverRequest(filter_tags=["nonexistent"])
        resp = echo_skill.handle(req)
        assert len(resp.skills) == 0

    def test_discover_with_category_filter(self, echo_skill):
        req = SkillDiscoverRequest(filter_categories=["test"])
        resp = echo_skill.handle(req)
        assert len(resp.skills) == 0  # echo_skill has no category

    def test_discover_error_is_handled(self, echo_skill):
        with patch.object(echo_skill, "_list_skills", side_effect=RuntimeError("boom")):
            req = SkillDiscoverRequest()
            resp = echo_skill.handle(req)
            assert isinstance(resp, A2EError)


class TestCall:
    def test_call_echo_skill_success(self, echo_skill):
        req = SkillCallRequest(
            name="echo_skill",
            arguments={"hello": "world"},
        )
        resp = echo_skill.handle(req)
        assert isinstance(resp, SkillCallResponse)
        assert resp.data.success is True
        assert resp.data.data["echo"]["hello"] == "world"

    def test_call_failing_skill_returns_error(self, failing_skill):
        req = SkillCallRequest(
            name="failing_skill",
            arguments={},
        )
        resp = failing_skill.handle(req)
        assert isinstance(resp, A2EError)
        assert "failed" in resp.message


class TestStreamingEvents:
    def test_call_emits_progress_events(self, echo_skill):
        """_execute_skill calls emit_event which should send to host."""
        req = SkillCallRequest(
            name="echo_skill",
            arguments={"test": True},
            streaming=True,
        )
        echo_skill.handle(req)
        # The emit_event call inside call() should have sent an event
        assert len(echo_skill.host_instance.sent) >= 1
        sent_event = echo_skill.host_instance.sent[0]
        assert isinstance(sent_event, SkillEvent)
        assert sent_event.kind == "progress"
        assert sent_event.data["pct"] == 100

    def test_emit_event_sends_via_host(self, echo_skill):
        """emit_event() should route through the host's _send."""
        events_before = len(echo_skill.host_instance.sent)
        evt = SkillEvent(kind="status", data={"msg": "test"}, req_id="r1")
        echo_skill.emit_event(evt)
        assert len(echo_skill.host_instance.sent) == events_before + 1

    def test_event_has_req_id(self, echo_skill):
        """Events emitted during skill call should have the request's id."""
        req = SkillCallRequest(
            name="echo_skill",
            arguments={"x": 1},
        )
        echo_skill.handle(req)
        sent = echo_skill.host_instance.sent
        for evt in sent:
            assert evt.req_id == req.id


class TestEventAggregation:
    def test_events_aggregated_in_response(self, echo_skill):
        """SkillCallResponse should not contain events (they're streamed separately)."""
        req = SkillCallRequest(
            name="echo_skill",
            arguments={"x": 1},
        )
        resp = echo_skill.handle(req)
        assert isinstance(resp, SkillCallResponse)
        # Events are streamed, not embedded in response
        assert len(echo_skill.host_instance.sent) >= 1


class TestErrorHandling:
    def test_invalid_message_type(self, echo_skill):
        req = A2EMessage(type="invalid/type", id="r1")
        resp = echo_skill.handle(req)
        assert resp is None

    def test_call_with_missing_name(self, echo_skill):
        """Calling a non-existent skill (by name mismatch) should not crash."""
        req = SkillCallRequest(
            name="nonexistent",
            arguments={},
        )
        resp = echo_skill.handle(req)
        # The echo skill implementation doesn't validate name — it just echoes
        # but it should complete without crash
        assert resp is not None
