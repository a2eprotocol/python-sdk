"""Tests for the A2EPlugin base class and event emission API."""

import pytest
from pydantic import BaseModel

from a2e.core.plugins.interface import A2EPlugin
from a2e.caps.base.protocol import A2EEvent, A2EMessage, A2EError


# ── Test Helpers ────────────────────────────────────────────────

class MockHost:
    """Simulates A2EServerRuntimeExecutor for plugin testing."""

    def __init__(self):
        self.sent = []

    def _send(self, msg: A2EMessage):
        self.sent.append(msg)


class MinimalPlugin(A2EPlugin):
    name = "minimal"

    def supported_messages(self):
        return {}

    def handle(self, message):
        return None


# ── Tests ───────────────────────────────────────────────────────

class TestA2EPluginBase:
    def test_plugin_has_name(self):
        p = MinimalPlugin()
        assert p.name == "minimal"

    def test_setup_stores_host_and_config(self):
        host = MockHost()
        p = MinimalPlugin()
        p.setup(host, {"type": "test", "priority": 5, "exclusive": False})
        assert p.host_instance is host
        assert p.config["type"] == "test"
        assert p.config["priority"] == 5

    def test_setup_default_priority_and_exclusive(self):
        host = MockHost()
        p = MinimalPlugin()
        p.setup(host, {"type": "test"})
        assert p.priority == 0
        assert p.exclusive is False

    def test_caps_metadata(self):
        host = MockHost()
        p = MinimalPlugin()
        p.setup(host, {"type": "test_type", "priority": 3, "exclusive": True})
        meta = p.caps_metadata()
        assert meta["name"] == "minimal"
        assert meta["type"] == "test_type"
        assert meta["priority"] == 3
        assert meta["exclusive"] is True


class TestEmitEvent:
    def test_emit_event_sends_through_host(self):
        host = MockHost()
        p = MinimalPlugin()
        p.setup(host, {"type": "test"})
        evt = A2EEvent(kind="status", data={"msg": "hello"}, req_id="r1")
        p.emit_event(evt)
        assert len(host.sent) == 1
        assert host.sent[0].kind == "status"
        assert host.sent[0].req_id == "r1"

    def test_emit_event_no_op_without_host(self):
        p = MinimalPlugin()
        # No setup → no host_instance
        evt = A2EEvent(kind="status", data={})
        # Should not raise
        p.emit_event(evt)

    def test_emit_event_multiple_events(self):
        host = MockHost()
        p = MinimalPlugin()
        p.setup(host, {"type": "test"})
        for i in range(3):
            p.emit_event(A2EEvent(kind="progress", data={"seq": i}))
        assert len(host.sent) == 3
        assert host.sent[0].data["seq"] == 0
        assert host.sent[2].data["seq"] == 2

    def test_emit_event_preserves_event_type(self):
        host = MockHost()
        p = MinimalPlugin()
        p.setup(host, {"type": "test"})
        evt = A2EEvent(kind="log", data={"level": "info", "message": "test"})
        p.emit_event(evt)
        assert host.sent[0].type == "invoke/event"

    def test_emit_event_with_none_host(self):
        """When host_instance has no _send, emit_event should not crash."""
        p = MinimalPlugin()

        class BadHost:
            pass

        p.setup(BadHost(), {"type": "test"})
        p.emit_event(A2EEvent(kind="status", data={}))  # should not raise


class TestTeardown:
    def test_teardown_default_does_nothing(self):
        p = MinimalPlugin()
        p.teardown()  # should not raise

    def test_teardown_called_on_stop(self):
        """Subclasses can override teardown; base impl does nothing."""
        called = []

        class TrackingPlugin(MinimalPlugin):
            def teardown(self):
                called.append(True)

        p = TrackingPlugin()
        p.teardown()
        assert called == [True]


class TestAuditHandle:
    def test_audit_handle_no_op_without_audit(self):
        """Without audit_log configured, audit_handle should not crash."""
        host = MockHost()
        p = MinimalPlugin()
        p.setup(host, {"type": "test"})
        # No _audit configured — should be no-op
        p.audit_handle(
            A2EMessage(type="test", id="r1"),
            A2EEvent(kind="status", data={}),
            "r1",
            0.0,
        )
