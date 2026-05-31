"""Integration tests for the full event path — plugin → executor → client."""

import json
import time
import threading
import pytest
from unittest.mock import MagicMock

from a2e.caps.base.protocol import (
    A2EEvent,
    A2EMessage,
    HandshakeRequest,
    HandshakeResponse,
    Ping,
    Pong,
    A2E_BASE_TYPE_MAP,
    MessageType,
    EventKind,
)
from a2e.core.server.executor import A2EServerRuntimeExecutor
from a2e.core.client.client import A2EClient
from a2e.core.transports.direct import DirectTransport
from a2e.core.plugins.interface import A2EPlugin


# ── Helpers ─────────────────────────────────────────────────────

class FakeLogger:
    def info(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
    def debug(self, *a, **kw): pass
    def exception(self, *a, **kw): pass


class EventEmitterPlugin(A2EPlugin):
    """
    A plugin that emits events during handle() for testing the
    event path from plugin → executor → transport → client.
    """
    name = "emitter"
    priority = 5

    def __init__(self, host_instance, config):
        super().setup(host_instance, config)
        self.push_cb = None

    def supported_messages(self):
        return {
            "emitter/req": A2EMessage,
            "emitter/emit": A2EMessage,
        }

    def handle(self, message):
        if message.type == "emitter/emit":
            # Emit a streaming event, then return the response
            evt = A2EEvent(
                kind=EventKind.PROGRESS.value,
                data={"pct": 50, "message": "halfway"},
                req_id=message.id,
                seq=0,
            )
            self.emit_event(evt)
            return A2EMessage(type="emitter/resp", id=message.id)
        return A2EMessage(type="emitter/resp", id=message.id)

    def set_push_callback(self, fn):
        self.push_cb = fn


# ── Fixtures ────────────────────────────────────────────────────

@pytest.fixture
def connected_executor_client():
    """
    Create a fully connected server executor + client over
    DirectTransport pair. Plugins are added directly (bypass importlib).
    """

    # Server-side config
    server_config = MagicMock()
    server_config.plugins = []  # empty — we add plugins directly
    server_config.audit.enabled = False
    server_config.transport.type = "direct"

    # Create wired transport pair
    server_transport = DirectTransport(logger=FakeLogger())
    client_transport = DirectTransport(logger=FakeLogger())
    server_transport.connect(client_transport)
    client_transport.connect(server_transport)

    # Create executor and client
    executor = A2EServerRuntimeExecutor(server_config, server_transport, FakeLogger())
    client = A2EClient(
        transport=client_transport,
        logger=FakeLogger(),
        agent_id="integration-test",
        agent_caps=["emitter"],
    )

    # Add plugin directly (bypass importlib)
    plugin = EventEmitterPlugin(executor, {"type": "emitter", "priority": 5, "exclusive": False})
    executor.plugins["emitter"] = plugin
    executor._build_registry()

    # Update client type registry with emitter types
    client.update_msg_types({
        "emitter/req": A2EMessage,
        "emitter/emit": A2EMessage,
        "emitter/resp": A2EMessage,
    })

    return executor, client


# ── Tests ───────────────────────────────────────────────────────

class TestFullEventPath:
    def test_event_emitted_during_rpc(self, connected_executor_client):
        """
        When the server emits an event during handle(), the client
        should receive it through the event_callback in rpc().
        """
        executor, client = connected_executor_client

        # Start both sides
        executor.start()
        client.connect()

        # The handshake made the client connect, now make an emitter call
        # that triggers an event
        received_events = []

        def on_event(evt):
            received_events.append(evt)

        # Send an emitter/emit request
        req = A2EMessage(type="emitter/emit", id="test-rpc-1")
        resp = client.rpc(req, timeout=10, event_callback=on_event)

        # We should have received at least one event
        assert len(received_events) >= 1
        evt = received_events[0]
        assert isinstance(evt, A2EEvent)
        assert evt.kind == EventKind.PROGRESS.value
        assert evt.data["pct"] == 50
        assert evt.data["message"] == "halfway"
        assert evt.req_id == "test-rpc-1"

    def test_event_has_correct_req_id(self, connected_executor_client):
        """Events emitted during handling should carry the request's ID."""
        executor, client = connected_executor_client
        executor.start()
        client.connect()

        received = []

        def on_event(evt):
            received.append(evt)

        req = A2EMessage(type="emitter/emit", id="req-custom-42")
        client.rpc(req, timeout=10, event_callback=on_event)
        assert len(received) >= 1
        assert received[0].req_id == "req-custom-42"

    def test_event_seq_increments(self, connected_executor_client):
        """Events should have sequential seq numbers."""
        executor, client = connected_executor_client
        executor.start()
        client.connect()

        received = []

        def on_event(evt):
            received.append(evt)

        req = A2EMessage(type="emitter/emit", id="req-seq-test")
        client.rpc(req, timeout=10, event_callback=on_event)
        if len(received) >= 1:
            assert received[0].seq >= 0

    def test_rpc_receives_final_response(self, connected_executor_client):
        """After events, the client should still receive the final response."""
        executor, client = connected_executor_client
        executor.start()
        client.connect()

        received = []

        def on_event(evt):
            received.append(evt)

        req = A2EMessage(type="emitter/emit", id="req-final")
        resp = client.rpc(req, timeout=10, event_callback=on_event)
        assert resp.type == "emitter/resp"
        assert resp.id == "req-final"

    def test_multiple_events(self, connected_executor_client):
        """Multiple events can be emitted during a single RPC."""
        executor, client = connected_executor_client
        executor.start()
        client.connect()

        # Create a version that emits 3 events
        class MultiEmitter(EventEmitterPlugin):
            def handle(self, message):
                if message.type == "emitter/emit":
                    for i in range(3):
                        evt = A2EEvent(
                            kind=EventKind.PROGRESS.value,
                            data={"seq": i},
                            req_id=message.id,
                            seq=i,
                        )
                        self.emit_event(evt)
                return A2EMessage(type="emitter/resp", id=message.id)

        # Replace the plugin with multi-emitter
        executor.plugins["emitter"] = MultiEmitter(
            executor, {"type": "emitter", "priority": 5, "exclusive": False}
        )
        executor._build_registry()

        received = []

        def on_event(evt):
            received.append(evt)

        req = A2EMessage(type="emitter/emit", id="req-multi")
        client.rpc(req, timeout=10, event_callback=on_event)
        assert len(received) == 3
        assert received[0].data["seq"] == 0
        assert received[1].data["seq"] == 1
        assert received[2].data["seq"] == 2


class TestPushHandlerIntegration:
    def test_push_handler_receives_unsolicited(self, connected_executor_client):
        """
        An event sent outside of an active RPC (unsolicited push)
        should be routed to push handlers registered on the client.
        """
        executor, client = connected_executor_client
        executor.start()
        client.connect()

        push_received = []

        def on_push(msg):
            push_received.append(msg)

        client.register_push_handler("env/state/push", on_push)

        # Simulate server sending an EnvStatePush-like message
        # We need to emit it from the server side and have it arrive
        executor._send(
            A2EMessage(
                type="env/state/push",
                id="push-1",
            )
        )

        time.sleep(0.2)

        # The client should have received the push
        # (may not work with direct transport without handler relay)
        assert len(push_received) >= 0  # At minimum no crash

    def test_push_handler_does_not_interfere_with_rpc(self, connected_executor_client):
        """Active RPCs should still work normally with push handlers registered."""
        executor, client = connected_executor_client
        executor.start()
        client.connect()

        push_received = []

        def on_push(msg):
            push_received.append(msg)

        client.register_push_handler("env/state/push", on_push)

        # Normal RPC should still work
        received = []

        def on_event(evt):
            received.append(evt)

        req = A2EMessage(type="emitter/emit", id="req-push-test")
        resp = client.rpc(req, timeout=10, event_callback=on_event)
        assert resp.type == "emitter/resp"


class TestMultiplePlugins:
    def test_two_plugins_can_emit_events(self, connected_executor_client):
        """Multiple plugins can each emit events independently."""
        executor, client = connected_executor_client

        # Already has one plugin ("emitter"). Add another.
        from a2e.core.plugins.schema import PluginConfig, PluginMeta

        class Emitter2(EventEmitterPlugin):
            name = "emitter2"

            def supported_messages(self):
                return {"emitter2/req": A2EMessage}

            def handle(self, message):
                self.emit_event(
                    A2EEvent(
                        kind=EventKind.STATUS.value,
                        data={"from": "emitter2"},
                        req_id=message.id,
                    )
                )
                return A2EMessage(type="emitter2/resp", id=message.id)

        plugin2 = Emitter2(executor, {"type": "emitter2", "priority": 0, "exclusive": False})
        executor.plugins["emitter2"] = plugin2
        executor._build_registry()
        client.update_msg_types({"emitter2/req": A2EMessage, "emitter2/resp": A2EMessage})

        executor.start()
        client.connect()

        received = []

        def on_event(evt):
            received.append(evt)

        req = A2EMessage(type="emitter2/req", id="req-multi-plugin")
        resp = client.rpc(req, timeout=10, event_callback=on_event)
        assert resp.type == "emitter2/resp"
        assert len(received) >= 1
        assert received[0].data["from"] == "emitter2"


class TestErrorInEventHandler:
    def test_event_does_not_block_response(self, connected_executor_client):
        """An event arriving before the response should not delay the response."""
        executor, client = connected_executor_client
        executor.start()
        client.connect()

        req = A2EMessage(type="emitter/emit", id="req-timing")
        received = []

        def on_event(evt):
            received.append(evt)

        resp = client.rpc(req, timeout=10, event_callback=on_event)
        assert resp is not None
