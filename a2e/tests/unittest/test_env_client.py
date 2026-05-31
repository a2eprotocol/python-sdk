"""Tests for EnvAPI — client-side environment interaction API."""

import json
import pytest
from unittest.mock import MagicMock

from a2e.caps.env.client import EnvAPI
from a2e.caps.env.protocol import (
    EnvStatePush,
    EnvStepResponse,
    EnvResetResponse,
    EnvObserveResponse,
    EnvCloseResponse,
    EnvObservation,
    EnvState,
    MessageType,
)
from a2e.caps.base.protocol import A2EEvent
from a2e.core.client.client import A2EClient


# ── Helpers ─────────────────────────────────────────────────────

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
        pass

    def send(self, msg: str):
        self.sent.append(msg)


class FakeLogger:
    def info(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
    def debug(self, *a, **kw): pass
    def exception(self, *a, **kw): pass


@pytest.fixture
def client():
    transport = MockTransport()
    logger = FakeLogger()
    return A2EClient(transport=transport, logger=logger, agent_id="test-agent")


@pytest.fixture
def env_api(client):
    api = EnvAPI(client)
    return api


@pytest.fixture
def handshaken_client(client):
    """A client that has completed handshake."""
    client._alive = True
    def mock_send(msg):
        data = client.encode(msg)
        d = json.loads(data)
        if d["type"] == "handshake/req":
            client._on_message(
                json.dumps({
                    "type": "handshake/resp",
                    "req_id": d["id"],
                    "session_id": "sess-test",
                    "ok": True,
                    "accepted_caps": [],
                })
            )

    client._send = mock_send
    client._handshake()
    return client


@pytest.fixture
def env_api_ready(handshaken_client):
    return EnvAPI(handshaken_client)


# ── Tests ───────────────────────────────────────────────────────

class TestEnvAPIConstruction:
    def test_init_updates_msg_types(self, client):
        api = EnvAPI(client)
        assert MessageType.ENV_RESET_REQ.value in client._type_registry
        assert MessageType.ENV_STATE_PUSH.value in client._type_registry
        assert MessageType.ENV_STEP_REQ.value in client._type_registry

    def test_init_registers_push_handler(self, client):
        api = EnvAPI(client)
        assert MessageType.ENV_STATE_PUSH.value in client._push_handlers
        assert len(client._push_handlers[MessageType.ENV_STATE_PUSH.value]) >= 1


class TestPushHandlerRegistration:
    def test_on_push_registers_callback(self, env_api):
        called = []

        def cb(msg):
            called.append(msg)

        env_api.on_push(cb)
        assert len(env_api._env_push_cbs) == 1

    def test_push_callback_invoked(self, env_api):
        """Simulate an incoming EnvStatePush through the client."""
        # Register the EnvStatePush type so decode knows about it
        from a2e.caps.env.protocol import EnvStatePush as ESP
        env_api._c.update_msg_types({"env/state/push": ESP})
        received = []

        def cb(msg):
            received.append(msg)

        env_api.on_push(cb)
        # Simulate transport delivering EnvStatePush
        env_api._c._on_message(
            json.dumps({
                "type": "env/state/push",
                "episode_id": "ep1",
                "step_id": 1,
                "event_type": "tool_result",
                "delta": {"result": "ok"},
            })
        )
        assert len(received) == 1
        assert received[0].event_type == "tool_result"
        assert received[0].episode_id == "ep1"

    def test_remove_push_callback(self, env_api):
        cb = lambda msg: None
        env_api.on_push(cb)
        env_api.remove_push_callback(cb)
        assert len(env_api._env_push_cbs) == 0


class TestReset:
    def test_reset_sends_request(self, env_api_ready):
        env_api_ready._c._send = lambda msg: (
            env_api_ready._c._on_message(
                json.dumps({
                    "type": "env/reset/resp",
                    "req_id": json.loads(msg)["id"],
                    "obs": {
                        "episode_id": "ep1",
                        "step_num": 0,
                        "state": {"obs": "initial"},
                        "done": False,
                    },
                })
            )
        )
        resp = env_api_ready.reset(env_name="test_env", seed=42)
        assert isinstance(resp, EnvResetResponse)
        assert resp.obs.episode_id is not None


class TestStep:
    def test_step_sends_request(self, env_api_ready):
        env_api_ready._c._send = lambda msg: (
            env_api_ready._c._on_message(
                json.dumps({
                    "type": "env/step/resp",
                    "req_id": json.loads(msg)["id"],
                    "obs": {
                        "episode_id": "ep1",
                        "step_num": 1,
                        "state": {"obs": "after"},
                        "done": False,
                    },
                })
            )
        )
        resp = env_api_ready.step(episode_id="ep1", action={"type": "move"})
        assert isinstance(resp, EnvStepResponse)

    def test_step_with_custom_action(self, env_api_ready):
        action = {"type": "tool_call", "tool": "read_file", "args": {"path": "/tmp"}}
        env_api_ready._c._send = lambda msg: (
            env_api_ready._c._on_message(
                json.dumps({
                    "type": "env/step/resp",
                    "req_id": json.loads(msg)["id"],
                    "obs": {
                        "episode_id": "ep1",
                        "step_num": 1,
                        "state": {"result": "file content"},
                        "done": False,
                    },
                })
            )
        )
        resp = env_api_ready.step(episode_id="ep1", action=action)
        assert resp.obs.state["result"] == "file content"


class TestObserve:
    def test_observe_returns_observation(self, env_api_ready):
        env_api_ready._c._send = lambda msg: (
            env_api_ready._c._on_message(
                json.dumps({
                    "type": "env/observe/resp",
                    "req_id": json.loads(msg)["id"],
                    "obs": {
                        "episode_id": "ep1",
                        "step_num": 3,
                        "state": {"sensor": 42},
                        "done": False,
                    },
                })
            )
        )
        obs = env_api_ready.observe(episode_id="ep1")
        assert isinstance(obs, EnvObservation)
        assert obs.step_num == 3


class TestClose:
    def test_close_returns_response(self, env_api_ready):
        env_api_ready._c._send = lambda msg: (
            env_api_ready._c._on_message(
                json.dumps({
                    "type": "env/close/resp",
                    "req_id": json.loads(msg)["id"],
                    "closed": True,
                })
            )
        )
        resp = env_api_ready.close(episode_id="ep1")
        assert isinstance(resp, EnvCloseResponse)
        assert resp.closed is True


class TestIsDone:
    def test_is_done_true(self, env_api):
        assert env_api.is_done(done=True, truncated=False) is True
        assert env_api.is_done(done=False, truncated=True) is True

    def test_is_done_false(self, env_api):
        assert env_api.is_done(done=False, truncated=False) is False
