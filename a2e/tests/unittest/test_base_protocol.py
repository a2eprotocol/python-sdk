"""Tests for the base A2E protocol messages and type registry."""

import json
import pytest
from pydantic import ValidationError

from a2e.caps.base.protocol import (
    A2EMessage,
    A2EEvent,
    A2EError,
    A2EErrorCode,
    HandshakeRequest,
    HandshakeResponse,
    HandshakeResponse,
    Ping,
    Pong,
    Shutdown,
    A2E_BASE_TYPE_MAP,
    MessageType,
    EventKind,
    Capability,
    A2ECapability,
)


class TestA2EMessageBase:
    def test_message_has_id(self):
        m = A2EMessage(type="test")
        assert len(m.id) == 32  # uuid hex
        assert m.version == "1.0"

    def test_message_has_timestamp(self):
        m = A2EMessage(type="test")
        assert m.ts > 0

    def test_to_dict(self):
        m = A2EMessage(type="test", id="abc")
        d = m.to_dict()
        assert d["type"] == "test"
        assert d["id"] == "abc"
        assert d["version"] == "1.0"

    def test_new_id_static(self):
        id1 = A2EMessage.new_id()
        id2 = A2EMessage.new_id()
        assert len(id1) == 32
        assert id1 != id2


class TestA2EEvent:
    def test_default_kind_is_status(self):
        evt = A2EEvent()
        assert evt.kind == EventKind.STATUS.value

    def test_default_type_is_invoke_event(self):
        evt = A2EEvent()
        assert evt.type == MessageType.INVOKE_EVT.value

    def test_event_with_req_id(self):
        evt = A2EEvent(
            kind=EventKind.PROGRESS.value,
            data={"pct": 50, "message": "halfway"},
            req_id="req-123",
            seq=1,
        )
        assert evt.req_id == "req-123"
        assert evt.data["pct"] == 50
        assert evt.seq == 1

    def test_all_event_kinds(self):
        for kind in EventKind:
            evt = A2EEvent(kind=kind.value, data={"test": True})
            assert evt.kind == kind.value

    def test_progress_event_shape(self):
        evt = A2EEvent(
            kind=EventKind.PROGRESS.value,
            data={"pct": 100, "message": "done"},
        )
        assert evt.data["pct"] == 100
        assert evt.data["message"] == "done"


class TestBaseTypeRegistry:
    def test_all_base_types_registered(self):
        """Every base MessageType has a corresponding class registered."""
        expected = {
            MessageType.HANDSHAKE_REQ.value,
            MessageType.HANDSHAKE_RESP.value,
            MessageType.PING.value,
            MessageType.PONG.value,
            MessageType.SHUTDOWN.value,
            MessageType.ERROR.value,
            MessageType.INVOKE_EVT.value,
        }
        registered = set(A2E_BASE_TYPE_MAP.keys())
        for t in expected:
            assert t in registered, f"{t} missing from A2E_BASE_TYPE_MAP"

    def test_decode_handshake_request(self):
        raw = json.dumps({"type": "handshake/req", "agent_id": "agent-a"})
        cls = A2E_BASE_TYPE_MAP["handshake/req"]
        msg = cls.model_validate(json.loads(raw))
        assert isinstance(msg, HandshakeRequest)
        assert msg.agent_id == "agent-a"

    def test_decode_handshake_response(self):
        raw = json.dumps({"type": "handshake/resp", "session_id": "sess-1", "ok": True})
        cls = A2E_BASE_TYPE_MAP["handshake/resp"]
        msg = cls.model_validate(json.loads(raw))
        assert isinstance(msg, HandshakeResponse)
        assert msg.session_id == "sess-1"

    def test_decode_ping(self):
        raw = json.dumps({"type": "ping"})
        cls = A2E_BASE_TYPE_MAP["ping"]
        msg = cls.model_validate(json.loads(raw))
        assert isinstance(msg, Ping)

    def test_decode_pong(self):
        raw = json.dumps({"type": "pong", "req_id": "abc", "uptime_seconds": 42.0})
        cls = A2E_BASE_TYPE_MAP["pong"]
        msg = cls.model_validate(json.loads(raw))
        assert isinstance(msg, Pong)
        assert msg.uptime_seconds == 42.0

    def test_decode_error(self):
        raw = json.dumps({
            "type": "error",
            "code": "parse_error",
            "message": "bad json",
            "req_id": "r1",
        })
        cls = A2E_BASE_TYPE_MAP["error"]
        msg = cls.model_validate(json.loads(raw))
        assert isinstance(msg, A2EError)
        assert msg.code == A2EErrorCode.PARSE_ERROR

    def test_decode_invoke_event(self):
        raw = json.dumps({
            "type": "invoke/event",
            "kind": "progress",
            "data": {"pct": 75},
            "req_id": "r1",
            "seq": 2,
        })
        cls = A2E_BASE_TYPE_MAP["invoke/event"]
        msg = cls.model_validate(json.loads(raw))
        assert isinstance(msg, A2EEvent)
        assert msg.kind == "progress"
        assert msg.data["pct"] == 75
        assert msg.seq == 2

    def test_unknown_type_raises(self):
        """An unknown type should result in None from the dict, not a lookup."""
        cls = A2E_BASE_TYPE_MAP.get("nonexistent/type")
        assert cls is None

    def test_round_trip_encode_decode(self):
        """A2EEvent serialized and deserialized should match."""
        orig = A2EEvent(
            kind=EventKind.LOG.value,
            data={"level": "info", "message": "test"},
            req_id="req-42",
            seq=5,
        )
        raw = json.dumps(orig.to_dict(), separators=(",", ":"), default=str)
        data = json.loads(raw)
        cls = A2E_BASE_TYPE_MAP[data["type"]]
        restored = cls.model_validate(data)
        assert restored.kind == orig.kind
        assert restored.req_id == orig.req_id
        assert restored.seq == orig.seq
        assert restored.data == orig.data


class TestHandshake:
    def test_handshake_request_defaults(self):
        req = HandshakeRequest()
        assert req.agent_id == ""
        assert req.agent_caps == []
        assert req.auth_token == ""

    def test_handshake_response_defaults(self):
        resp = HandshakeResponse()
        assert resp.ok is True
        assert resp.max_parallel == 4
        assert resp.session_id != ""

    def test_handshake_response_with_caps(self):
        cap = Capability(capability=A2ECapability.SKILL, enabled=True)
        resp = HandshakeResponse(accepted_caps=[cap])
        assert resp.accepted_caps[0].capability == A2ECapability.SKILL

    def test_handshake_response_failure(self):
        resp = HandshakeResponse(ok=False, reason="bad token")
        assert resp.ok is False
        assert resp.reason == "bad token"


class TestA2EError:
    def test_error_defaults(self):
        err = A2EError(code="parse_error")
        assert err.type == MessageType.ERROR.value
        assert err.retryable is False
        assert err.req_id == ""

    def test_error_with_detail(self):
        err = A2EError(
            code="runtime_error",
            message="Segfault",
            detail={"line": 42},
            retryable=True,
            req_id="req-1",
        )
        assert err.code == A2EErrorCode.RUNTIME_ERROR
        assert err.detail["line"] == 42
        assert err.retryable is True


class TestLifecycleMessages:
    def test_ping(self):
        p = Ping()
        assert p.type == MessageType.PING.value

    def test_pong(self):
        p = Pong(req_id="r1", uptime_seconds=10.5)
        assert p.req_id == "r1"
        assert p.uptime_seconds == 10.5

    def test_shutdown_default_timeout(self):
        s = Shutdown()
        assert s.timeout == 10

    def test_shutdown_custom_timeout(self):
        s = Shutdown(timeout=30)
        assert s.timeout == 30


class TestCapability:
    def test_capability_default_enabled(self):
        c = Capability(capability=A2ECapability.SKILL)
        assert c.enabled is True

    def test_capability_disabled(self):
        c = Capability(capability=A2ECapability.TOOLS, enabled=False)
        assert c.enabled is False

    def test_capability_with_metadata(self):
        c = Capability(
            capability=A2ECapability.ENV,
            metadata={"version": "1.0"},
        )
        assert c.metadata["version"] == "1.0"
