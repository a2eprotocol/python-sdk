"""Tests for ProcPlugin — process lifecycle management plugin."""

import json
import pytest
from unittest.mock import MagicMock, patch

from a2e.caps.proc.plugin import ProcPlugin
from a2e.caps.proc.protocol import (
    ProcSpawnRequest,
    ProcSpawnResponse,
    ProcWriteRequest,
    ProcWriteResponse,
    ProcKillRequest,
    ProcKillResponse,
    ProcStatusRequest,
    ProcStatusResponse,
    ProcReadEvent,
    MessageType,
)
from a2e.caps.base.protocol import (
    A2EError,
    A2EErrorCode,
    A2EMessage,
)


# ── Helpers ─────────────────────────────────────────────────────

class MockHost:
    def __init__(self):
        self.sent = []

    def _send(self, msg):
        self.sent.append(msg)


@pytest.fixture
def proc_plugin():
    host = MockHost()
    config = {
        "type": "proc",
        "priority": 5,
        "exclusive": False,
        "ALLOWED_COMMANDS": {"python3", "bash", "ls", "echo"},
    }
    return ProcPlugin(host, config)


# ── Tests ───────────────────────────────────────────────────────

class TestProcPluginInit:
    def test_init_empty_sessions(self, proc_plugin):
        assert proc_plugin.sessions == {}

    def test_supported_messages(self, proc_plugin):
        msgs = proc_plugin.supported_messages()
        assert MessageType.PROC_SPAWN_REQ in msgs
        assert MessageType.PROC_WRITE_REQ in msgs
        assert MessageType.PROC_KILL_REQ in msgs
        assert MessageType.PROC_STATUS_REQ in msgs


class TestSpawnValidation:
    def test_spawn_empty_command_returns_error(self, proc_plugin):
        req = ProcSpawnRequest(cmd=[])
        resp = proc_plugin.handle(req)
        assert isinstance(resp, ProcSpawnResponse)
        assert resp.ok is False
        assert "Empty command" in resp.error

    def test_spawn_non_list_command_returns_error(self, proc_plugin):
        req = MagicMock()
        req.cmd = "not a list"
        req.id = "r1"
        # The plugin checks isinstance(cmd, list)
        resp = proc_plugin._spawn(req)
        assert isinstance(resp, ProcSpawnResponse)
        assert resp.ok is False

    def test_spawn_disallowed_command_returns_error(self, proc_plugin):
        req = ProcSpawnRequest(cmd=["rm", "-rf", "/"])
        resp = proc_plugin.handle(req)
        assert isinstance(resp, ProcSpawnResponse)
        assert resp.ok is False
        assert "not allowed" in resp.error

    def test_spawn_allowed_command_succeeds(self, proc_plugin):
        req = ProcSpawnRequest(cmd=["echo", "hello"])
        resp = proc_plugin.handle(req)
        assert isinstance(resp, ProcSpawnResponse)
        assert resp.ok is True
        assert resp.proc_id != ""


class TestSpawnRealProcess:
    def test_spawn_creates_session(self, proc_plugin):
        req = ProcSpawnRequest(cmd=["echo", "hello"])
        resp = proc_plugin.handle(req)
        assert resp.proc_id in proc_plugin.sessions

    def test_spawn_process_has_pid(self, proc_plugin):
        req = ProcSpawnRequest(cmd=["echo", "hello"])
        resp = proc_plugin.handle(req)
        assert resp.pid > 0

    def test_spawn_with_cwd(self, proc_plugin):
        req = ProcSpawnRequest(cmd=["echo", "hi"], cwd="/tmp")
        resp = proc_plugin.handle(req)
        assert resp.ok is True

    def test_spawn_with_env_vars(self, proc_plugin):
        req = ProcSpawnRequest(cmd=["sh", "-c", "echo $MY_VAR"], env={"MY_VAR": "test"})
        resp = proc_plugin.handle(req)
        assert resp.ok is True


class TestWrite:
    def test_write_to_nonexistent_process(self, proc_plugin):
        req = ProcWriteRequest(proc_id="nonexistent", data="hello")
        resp = proc_plugin.handle(req)
        assert isinstance(resp, ProcWriteResponse)
        assert "not found" in resp.error


class TestKill:
    def test_kill_nonexistent_process(self, proc_plugin):
        req = ProcKillRequest(proc_id="nonexistent")
        resp = proc_plugin.handle(req)
        assert isinstance(resp, ProcKillResponse)
        assert resp.ok is False


class TestStatus:
    def test_status_nonexistent_process(self, proc_plugin):
        req = ProcStatusRequest(proc_id="nonexistent")
        resp = proc_plugin.handle(req)
        assert isinstance(resp, ProcStatusResponse)
        assert resp.status == "not_found"

    def test_status_running_process(self, proc_plugin):
        req = ProcSpawnRequest(cmd=["echo", "hello"])
        spawn_resp = proc_plugin.handle(req)
        status_req = ProcStatusRequest(proc_id=spawn_resp.proc_id)
        status_resp = proc_plugin.handle(status_req)
        assert isinstance(status_resp, ProcStatusResponse)
        assert status_resp.status != ""


class TestErrorHandling:
    def test_invalid_message_type(self, proc_plugin):
        req = A2EMessage(type="invalid/type", id="r1")
        resp = proc_plugin.handle(req)
        assert isinstance(resp, A2EError)

    def test_spawn_error_wraps_to_response(self, proc_plugin):
        """When spawn raises, it should return an error response, not crash."""
        req = ProcSpawnRequest(cmd=["python3", "-c", "import does_not_exist"])
        resp = proc_plugin.handle(req)
        assert isinstance(resp, ProcSpawnResponse)
        # This might fail or succeed depending on whether python3 raises
        # The point is it shouldn't crash the plugin


class TestEventEmission:
    def test_emit_event_sends_through_host(self, proc_plugin):
        """After spawn, process output should trigger emit_event through host."""
        import time

        req = ProcSpawnRequest(cmd=["echo", "hello_world"])
        spawn_resp = proc_plugin.handle(req)
        assert spawn_resp.ok is True

        # Give the background thread time to read output
        time.sleep(0.3)

        # Should have at least one event sent (the stdout line + possibly exit)
        assert len(proc_plugin.host_instance.sent) >= 1
        first = proc_plugin.host_instance.sent[0]
        # The sent event could be a ProcReadEvent
        assert isinstance(first, ProcReadEvent) or hasattr(first, "proc_id")

    def test_emit_event_uses_emit_event_api(self, proc_plugin):
        """_emit_event should send through emit_event() on the base class."""
        with patch.object(proc_plugin, "emit_event") as mock_emit:
            req = ProcSpawnRequest(cmd=["echo", "test_emit"])
            proc_plugin.handle(req)
            import time
            time.sleep(0.3)
            assert mock_emit.called


class TestAllowedCommands:
    def test_custom_allowed_commands(self):
        host = MockHost()
        config = {
            "type": "proc",
            "priority": 5,
            "exclusive": False,
            "ALLOWED_COMMANDS": {"python3"},
        }
        plugin = ProcPlugin(host, config)
        assert "python3" in plugin.allowed_commands
        assert "bash" not in plugin.allowed_commands
