"""Tests for the A2E client (agent-side)."""

import json
import queue
import time as time_module
import pytest

from a2e.core.client.client import A2EClient, A2EClientError
from a2e.caps.base.protocol import (
    A2EEvent,
    A2EError,
    A2EMessage,
    HandshakeRequest,
    HandshakeResponse,
    Ping,
    Pong,
    Shutdown,
    A2E_BASE_TYPE_MAP,
    MessageType,
)


class MockTransport:
    def __init__(self):
        self.handler = None
        self.started = False
        self.stopped = False
        self.sent = []

    def set_message_handler(self, handler):
        self.handler = handler
    def start(self):
        self.started = True
    def stop(self):
        self.stopped = True
    def send(self, msg: str):
        self.sent.append(msg)


class FakeLogger:
    def info(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
    def debug(self, *a, **kw): pass
    def exception(self, *a, **kw): pass


def make_client(transport=None):
    t = transport or MockTransport()
    client = A2EClient(transport=t, logger=FakeLogger(), agent_id="test-agent")
    client._alive = True  # allow _send to work without full connect
    return client


def req_id_from_msg(msg):
    """Extract id from an A2EMessage by encoding to JSON first."""
    return json.loads(json.dumps(msg.to_dict(), default=str))["id"]


def make_handshake_responder(client):
    """Patch _send to auto-respond to handshake requests."""
    def patched_send(msg):
        if isinstance(msg, HandshakeRequest):
            client._on_message(json.dumps({
                "type": "handshake/resp",
                "req_id": msg.id,
                "session_id": "sess-test",
                "ok": True,
                "accepted_caps": [],
            }))
        else:
            # For non-handshake messages, encode and send via transport
            client._transport.send(client.encode(msg))
    client._send = patched_send


# ── Tests ───────────────────────────────────────────────────────

class TestA2EClientInit:
    def test_default_agent_id(self):
        assert make_client()._agent_id != ""

    def test_default_caps(self):
        c = make_client()
        assert "streaming" in c._agent_caps

    def test_type_registry_contains_base_types(self):
        c = make_client()
        for key in A2E_BASE_TYPE_MAP:
            assert key in c._type_registry

    def test_update_msg_types(self):
        c = make_client()
        c.update_msg_types({"test/type": A2EMessage})
        assert "test/type" in c._type_registry

    def test_push_handlers_empty_init(self):
        assert make_client()._push_handlers == {}


class TestPushHandler:
    def test_register_push_handler(self):
        c = make_client()
        cb = lambda m: None
        c.register_push_handler("t", cb)
        assert cb in c._push_handlers["t"]

    def test_unregister_push_handler(self):
        c = make_client()
        cb = lambda m: None
        c.register_push_handler("t", cb)
        c.unregister_push_handler("t", cb)
        assert len(c._push_handlers["t"]) == 0

    def test_push_handler_invoked_on_message(self):
        c = make_client()
        c.update_msg_types({"test/push": A2EMessage})
        received = []
        c.register_push_handler("test/push", lambda m: received.append(m))
        c._on_message(json.dumps({"type": "test/push", "id": "x"}))
        assert len(received) == 1

    def test_push_handler_not_invoked_for_pending_rpc(self):
        c = make_client()
        push_received = []
        c.register_push_handler("handshake/resp", lambda m: push_received.append(m))
        q = queue.Queue()
        c._pending["req-1"] = q
        c._on_message(json.dumps({"type": "handshake/resp", "req_id": "req-1",
                                   "session_id": "s", "ok": True, "accepted_caps": []}))
        assert len(push_received) == 0
        assert q.get(timeout=0.1) is not None


class TestOnMessage:
    def test_empty_message_ignored(self):
        make_client()._on_message("")

    def test_bad_json_ignored(self):
        make_client()._on_message("not json")

    def test_message_routed_to_pending(self):
        c = make_client()
        q = queue.Queue()
        c._pending["r1"] = q
        c._on_message(json.dumps({"type": "handshake/resp", "req_id": "r1",
                                   "session_id": "s", "ok": True, "accepted_caps": []}))
        assert isinstance(q.get(timeout=0.1), HandshakeResponse)

    def test_unknown_type_defaults_to_a2emessage(self):
        msg = make_client().decode(json.dumps({"type": "unknown/type", "id": "abc"}))
        assert isinstance(msg, A2EMessage)

    def test_events_routed_when_req_id_in_events(self):
        c = make_client()
        received = []
        c._events["req-1"] = [lambda m: received.append(m)]
        c._on_message(json.dumps({"type": "invoke/event", "kind": "progress",
                                   "data": {"pct": 50}, "req_id": "req-1", "seq": 0}))
        assert len(received) == 1
        assert received[0].kind == "progress"


class TestRPC:
    def test_rpc_sends_and_receives(self):
        c = make_client()
        req = Ping()
        def mock_send(msg):
            c._on_message(json.dumps({
                "type": "pong", "req_id": msg.id, "uptime_seconds": 1.0,
            }))
        c._send = mock_send
        resp = c.rpc(req, timeout=5)
        assert isinstance(resp, Pong)
        assert resp.uptime_seconds == 1.0

    def test_rpc_timeout(self):
        c = make_client()
        with pytest.raises(TimeoutError):
            c.rpc(Ping(), timeout=0.001)

    def test_rpc_error_raises_client_error(self):
        c = make_client()
        req = Ping()
        def mock_send(msg):
            c._on_message(json.dumps({
                "type": "error", "code": "runtime_error",
                "message": "something broke", "req_id": msg.id, "retryable": False,
            }))
        c._send = mock_send
        with pytest.raises(A2EClientError, match="something broke"):
            c.rpc(req, timeout=5)

    def test_rpc_collects_events_on_error(self):
        c = make_client()
        req = Ping()
        events = []
        def mock_send(msg):
            c._on_message(json.dumps({
                "type": "invoke/event", "kind": "progress",
                "data": {"pct": 10}, "req_id": msg.id, "seq": 0,
            }))
            c._on_message(json.dumps({
                "type": "error", "code": "runtime_error",
                "message": "fail", "req_id": msg.id, "retryable": False,
            }))
        c._send = mock_send
        with pytest.raises(A2EClientError):
            c.rpc(req, timeout=5, event_callback=lambda e: events.append(e))
        assert len(events) > 0


class TestHandshake:
    def test_handshake_success(self):
        c = make_client()
        c._send = lambda msg: c._on_message(json.dumps({
            "type": "handshake/resp", "req_id": msg.id,
            "session_id": "sess-test", "ok": True, "accepted_caps": [],
        }))
        c.connect()
        assert c._session_id == "sess-test"

    def test_handshake_failure_raises(self):
        c = make_client()
        c._send = lambda msg: c._on_message(json.dumps({
            "type": "handshake/resp", "req_id": msg.id,
            "ok": False, "reason": "bad auth",
        }))
        with pytest.raises(ConnectionError, match="Handshake failed"):
            c.connect()


class TestLifecycle:
    def test_connect_starts_transport(self):
        t = MockTransport()
        c = make_client(t)
        c._send = lambda msg: c._on_message(json.dumps({
            "type": "handshake/resp", "req_id": msg.id,
            "session_id": "s", "ok": True, "accepted_caps": [],
        }))
        c.connect()
        assert t.started is True

    def test_disconnect_sends_shutdown(self):
        t = MockTransport()
        c = make_client(t)
        c._send = lambda msg: c._on_message(json.dumps({
            "type": "handshake/resp", "req_id": msg.id,
            "session_id": "s", "ok": True, "accepted_caps": [],
        }))
        c.connect()
        # Restore the real _send method that encodes to JSON before sending
        real_send = A2EClient._send.__get__(c, A2EClient)
        c._send = real_send
        c.disconnect()
        # t.sent should now contain JSON strings, not A2EMessage objects
        assert any(
            json.loads(m).get("type") == "shutdown" for m in t.sent
        )

    def test_ping_returns_ms(self):
        c = make_client()
        def mock_send(msg):
            if isinstance(msg, Ping):
                c._on_message(json.dumps({
                    "type": "pong", "req_id": msg.id, "uptime_seconds": 0.1,
                }))
        c._send = mock_send
        ms = c.ping(timeout=5)
        assert ms > 0

    def test_encode_decode_round_trip(self):
        c = make_client()
        evt = A2EEvent(kind="status", data={"msg": "hi"}, req_id="r1")
        decoded = c.decode(c.encode(evt))
        assert decoded.kind == "status"
        assert decoded.req_id == "r1"

    def test_capabilities(self):
        c = make_client()
        c._send = lambda msg: c._on_message(json.dumps({
            "type": "handshake/resp", "req_id": msg.id,
            "session_id": "s", "ok": True,
            "accepted_caps": [{"capability": "skill", "enabled": True}],
        }))
        c.connect()
        assert c.capabilities()[0].capability == "skill"
