"""Tests for the A2E server executor — plugin loading, push wiring, dispatch."""

import json
import pytest
from unittest.mock import MagicMock

from a2e.core.server.executor import A2EServerRuntimeExecutor
from a2e.caps.base.protocol import (
    A2EEvent,
    A2EMessage,
    Ping,
    Pong,
    MessageType,
)
from a2e.core.plugins.interface import A2EPlugin
from a2e.core.plugins.schema import PluginConfig, PluginMeta


class MockTransport:
    def __init__(self):
        self.handler = None
        self.started = False
        self.sent = []

    def set_message_handler(self, handler):
        self.handler = handler

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def send(self, msg: str):
        self.sent.append(msg)


class FakeLogger:
    def info(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
    def debug(self, *a, **kw): pass
    def exception(self, *a, **kw): pass


class MockPlugin(A2EPlugin):
    name = "mock"
    priority = 5

    def __init__(self, host_instance, config):
        super().setup(host_instance, config)
        self.handle_calls = []
        self.push_callback = None

    def supported_messages(self):
        return {"mock/req": A2EMessage, "mock/resp": A2EMessage}

    def handle(self, message):
        self.handle_calls.append(message)
        return A2EMessage(type="mock/resp", id=message.id)

    def set_push_callback(self, fn):
        self.push_callback = fn

    def emit_via_push(self, event):
        if self.push_callback:
            self.push_callback(event)


class ExclusivePlugin(A2EPlugin):
    name = "exclusive"
    priority = 10
    exclusive = True

    def __init__(self, host_instance, config):
        super().setup(host_instance, config)

    def supported_messages(self):
        return {"exclusive/test": A2EMessage}

    def handle(self, message):
        return A2EMessage(type="exclusive/resp", id=message.id)


def make_executor():
    config = MagicMock()
    config.plugins = []
    config.audit.enabled = False
    return A2EServerRuntimeExecutor(config, MockTransport(), FakeLogger())


def add_plugin(executor, plugin):
    executor.plugins[plugin.name] = plugin
    executor._build_registry()


# ── Tests ───────────────────────────────────────────────────────

class TestPluginLoading:
    def test_no_plugins_loaded(self):
        ex = make_executor()
        ex._load_plugins()
        assert len(ex.plugins) == 0

    def test_disabled_plugin_skipped(self):
        ex = make_executor()
        ex._config.plugins = [
            PluginConfig(name="mock", type="mock", cls="any.module.MockPlugin",
                         metadata=PluginMeta(enabled=False)),
        ]
        ex._load_plugins()
        assert "mock" not in ex.plugins

    def test_push_callback_wired_directly(self):
        host = MagicMock()
        p = MockPlugin(host, {"type": "mock", "priority": 5, "exclusive": False})
        assert hasattr(p, "set_push_callback")

    def test_push_callback_sends_events(self):
        ex = make_executor()
        ex._alive = True
        p = MockPlugin(ex, {"type": "mock", "priority": 5, "exclusive": False})
        p.set_push_callback(ex._send)
        p.emit_via_push(A2EEvent(kind="status", data={"msg": "push test"}, req_id="r1"))
        assert len(ex.transport.sent) >= 1

    def test_push_callback_not_required(self):
        class NoPush(A2EPlugin):
            name = "nopush"
            def supported_messages(self): return {}
            def handle(self, msg): return None

        ex = make_executor()
        ex._alive = True
        p = NoPush()
        p.setup(ex, {"type": "nopush", "priority": 0, "exclusive": False})
        ex.plugins["nopush"] = p

    def test_build_registry(self):
        ex = make_executor()
        p = MockPlugin(ex, {"type": "mock", "priority": 5, "exclusive": False})
        ex.plugins["mock"] = p
        ex._build_registry()
        assert "mock/req" in ex.type_registry
        assert "mock/resp" in ex.type_registry
        assert "mock/req" in ex.type_to_plugins

    def test_base_types_in_registry(self):
        ex = make_executor()
        assert MessageType.PING.value in ex.type_registry


class TestDispatch:
    def test_dispatch_unknown_type_returns_error(self):
        ex = make_executor()
        ex._alive = True
        ex._load_plugins()
        ex._build_registry()
        ex.handle_raw(json.dumps({"type": "nonexistent/type", "id": "r1"}))
        assert len(ex.transport.sent) >= 1
        assert json.loads(ex.transport.sent[0])["type"] == "error"

    def test_dispatch_core_handshake(self):
        ex = make_executor()
        ex._alive = True
        ex.handle_raw(json.dumps({"type": "handshake/req", "agent_id": "test"}))
        sent = json.loads(ex.transport.sent[0])
        assert sent["type"] == "handshake/resp"

    def test_dispatch_core_ping(self):
        ex = make_executor()
        ex._alive = True
        ex.handle_raw(json.dumps({"type": "ping", "id": "p1"}))
        assert json.loads(ex.transport.sent[0])["type"] == "pong"

    def test_handle_core_shutdown(self):
        ex = make_executor()
        ex._alive = True
        ex.handle_raw(json.dumps({"type": "shutdown", "id": "s1"}))
        assert ex._alive is False

    def test_dispatch_to_plugin(self):
        ex = make_executor()
        ex._alive = True
        ex._load_plugins()
        p = MockPlugin(ex, {"type": "mock", "priority": 5, "exclusive": False})
        add_plugin(ex, p)
        ex.handle_raw(json.dumps({"type": "mock/req", "id": "m1"}))
        assert len(p.handle_calls) == 1

    def test_exclusive_plugin_used_first(self):
        ex = make_executor()
        ex._alive = True
        ex._load_plugins()
        ep = ExclusivePlugin(ex, {"type": "exclusive", "priority": 10, "exclusive": True})
        ex.plugins["exclusive"] = ep
        mp = MockPlugin(ex, {"type": "mock", "priority": 5, "exclusive": False})
        mp.supported_messages = lambda: {"exclusive/test": A2EMessage}
        ex.plugins["mock"] = mp
        ex._build_registry()
        ex.handle_raw(json.dumps({"type": "exclusive/test", "id": "e1"}))

    def test_decode_returns_base_model(self):
        ex = make_executor()
        msg = ex.decode(json.dumps({"type": "ping", "id": "p1", "version": "1.0", "ts": 0}))
        assert isinstance(msg, Ping)

    def test_encode_returns_json_string(self):
        ex = make_executor()
        encoded = ex.encode(A2EEvent(kind="status", data={"msg": "hi"}, req_id="r1"))
        data = json.loads(encoded)
        assert data["type"] == "invoke/event"
        assert data["kind"] == "status"
