"""Tests for EnvPlugin — environment simulation plugin."""

import pytest
from unittest.mock import MagicMock
from pydantic import BaseModel

from a2e.caps.env.plugin import EnvPlugin
from a2e.caps.env.protocol import (
    EnvResetRequest,
    EnvResetResponse,
    EnvStepRequest,
    EnvStepResponse,
    EnvObserveRequest,
    EnvObserveResponse,
    EnvCloseRequest,
    EnvCloseResponse,
    EnvStatePush,
    EnvObservation,
    EnvState,
    EnvAction,
    ENV_TYPE_MAP,
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


class CounterEnv(EnvPlugin):
    """A simple deterministic environment for testing."""
    name = "counter"

    def __init__(self, host_instance, config):
        super().__init__(host_instance, config)
        self.count = 0
        self.reset_count = 0

    def on_reset(self, seed=None, options=None):
        self.reset_count += 1
        self.count = 0
        return {"counter": 0, "label": "started"}

    def on_step(self, episode_id, action):
        self.count += 1
        done = self.count >= 5
        return EnvObservation(
            episode_id=episode_id,
            step_num=self.count,
            state={"counter": self.count},
            done=done,
        )

    def on_close(self):
        self.count = -1


@pytest.fixture
def counter_env():
    host = MockHost()
    env = CounterEnv(host, {"type": "env", "priority": 0, "exclusive": False})
    return env


# ── Tests ───────────────────────────────────────────────────────

class TestEnvPluginInit:
    def test_init_state(self, counter_env):
        assert counter_env._episode is None
        assert counter_env._active is False
        assert counter_env._store is None
        assert counter_env._push_cb is None

    def test_supported_messages(self, counter_env):
        msgs = counter_env.supported_messages()
        assert MessageType.ENV_RESET_REQ in msgs
        assert MessageType.ENV_STEP_REQ in msgs
        assert MessageType.ENV_OBSERVE_REQ in msgs
        assert MessageType.ENV_CLOSE_REQ in msgs


class TestEnvReset:
    def test_reset_returns_observation(self, counter_env):
        obs = counter_env.reset(seed=42)
        assert isinstance(obs, EnvObservation)
        assert obs.state.counter == 0
        assert obs.step_num == 0
        assert obs.done is False

    def test_reset_via_handle(self, counter_env):
        req = EnvResetRequest(env_name="counter", seed=42)
        resp = counter_env.handle(req)
        assert isinstance(resp, EnvResetResponse)
        assert resp.obs.state.counter == 0

    def test_reset_creates_episode(self, counter_env):
        counter_env.reset()
        assert counter_env._episode is not None
        assert counter_env._episode.id is not None

    def test_reset_closes_previous_episode(self, counter_env):
        counter_env.reset(seed=1)
        ep1_id = counter_env._episode.id
        counter_env.reset(seed=2)
        ep2_id = counter_env._episode.id
        assert ep1_id != ep2_id  # new episode


class TestEnvStep:
    def test_step_returns_observation(self, counter_env):
        counter_env.reset()
        action = {"action_type": "increment", "payload": {}}
        obs = counter_env.step(action)
        assert isinstance(obs, EnvObservation)
        assert obs.state.counter == 1

    def test_step_increments_step_num(self, counter_env):
        counter_env.reset()
        action = {"action_type": "increment", "payload": {}}
        obs1 = counter_env.step(action)
        obs2 = counter_env.step(action)
        assert obs1.step_num == 1
        assert obs2.step_num == 2

    def test_step_via_handle(self, counter_env):
        counter_env.reset()
        req = EnvStepRequest(
            episode_id=counter_env._episode.id,
            action={"action_type": "increment", "payload": {}},
        )
        resp = counter_env.handle(req)
        assert isinstance(resp, EnvStepResponse)
        assert resp.obs.state.counter == 1

    def test_step_after_done_raises(self, counter_env):
        counter_env.reset()
        for _ in range(5):
            action = {"action_type": "increment", "payload": {}}
            counter_env.step(action)

        # The 5th step would have triggered done in the test env
        # But the step_num in _Episode increments after each step
        # Let me check: on_step returns done=True when count >= 5 (i.e. the 5th step)
        # Actually the counter starts at 0, so after 5 steps, count=5 >= 5 → done
        # But the 6th step should error
        action = {"action_type": "increment", "payload": {}}
        with pytest.raises(RuntimeError, match="Episode already completed"):
            counter_env.step(action)

    def test_step_without_reset_raises(self, counter_env):
        action = {"action_type": "increment", "payload": {}}
        with pytest.raises(RuntimeError, match="No active episode"):
            counter_env.step(action)


class TestEnvObserve:
    def test_observe_returns_current_state(self, counter_env):
        counter_env.reset()
        obs = counter_env.observe()
        assert obs.step_num == 0

    def test_observe_after_steps(self, counter_env):
        counter_env.reset()
        action = {"action_type": "increment", "payload": {}}
        counter_env.step(action)
        counter_env.step(action)
        obs = counter_env.observe()
        assert obs.step_num == 2

    def test_observe_via_handle(self, counter_env):
        counter_env.reset()
        req = EnvObserveRequest(episode_id=counter_env._episode.id)
        resp = counter_env.handle(req)
        assert isinstance(resp, EnvObserveResponse)
        assert resp.obs.step_num == 0

    def test_observe_without_reset_raises(self, counter_env):
        with pytest.raises(RuntimeError, match="No active episode"):
            counter_env.observe()


class TestEnvClose:
    def test_close_clears_episode(self, counter_env):
        counter_env.reset()
        assert counter_env._episode is not None
        counter_env.close()
        assert counter_env._episode is None

    def test_close_via_handle(self, counter_env):
        counter_env.reset()
        req = EnvCloseRequest(episode_id=counter_env._episode.id)
        resp = counter_env.handle(req)
        assert isinstance(resp, EnvCloseResponse)
        assert resp.closed is True

    def test_close_without_reset(self, counter_env):
        counter_env.close()  # should not raise

    def test_close_calls_on_close(self, counter_env):
        counter_env.reset()
        counter_env.close()
        assert counter_env.count == -1


class TestPushEvent:
    def test_push_callback_called(self, counter_env):
        received = []

        def cb(msg):
            received.append(msg)

        counter_env.set_push_callback(cb)
        counter_env.reset()
        counter_env.push(
            event_type="tool_result",
            delta={"result": "ok"},
            reason="test push",
        )
        assert len(received) == 1
        assert isinstance(received[0], EnvStatePush)
        assert received[0].event_type == "tool_result"

    def test_push_without_callback(self, counter_env):
        """Push should not crash even without a callback set."""
        counter_env.reset()
        counter_env.push(event_type="status", delta={"msg": "hi"})

    def test_push_callback_error_safe(self, counter_env):
        """Callback that raises should not crash the push method."""

        def bad_cb(msg):
            raise RuntimeError("callback failed")

        counter_env.set_push_callback(bad_cb)
        counter_env.reset()
        counter_env.push(event_type="status", delta={})  # should not crash

    def test_push_via_executor_wiring(self):
        """Simulate executor wiring — callback = host._send."""
        host = MockHost()
        env = CounterEnv(host, {"type": "env", "priority": 0, "exclusive": False})
        env.set_push_callback(host._send)
        env.reset()
        env.push(event_type="tool_result", delta={"data": "test"})
        assert len(host.sent) >= 1
        # The host is MockHost — _send is called with the EnvStatePush
        push_msg = host.sent[0]
        assert isinstance(push_msg, EnvStatePush)

    def test_push_episode_required(self, counter_env):
        """Push without active episode should not crash (graceful skip)."""
        counter_env.push(event_type="status", delta={})


class TestSpaces:
    def test_spaces_default(self, counter_env):
        spaces = counter_env.spaces()
        assert "action_space" in spaces
        assert "state_schema" in spaces


class TestRender:
    def test_render_text_mode(self, counter_env):
        counter_env.reset()
        rendered = counter_env.render(mode="text")
        assert rendered is not None
        assert "counter" in str(rendered)

    def test_render_json_mode(self, counter_env):
        counter_env.reset()
        rendered = counter_env.render(mode="json")
        assert isinstance(rendered, EnvState) or isinstance(rendered, dict)

    def test_render_unknown_mode(self, counter_env):
        counter_env.reset()
        rendered = counter_env.render(mode="invalid")
        assert rendered is None

    def test_render_without_episode(self, counter_env):
        with pytest.raises(RuntimeError):
            counter_env.render()
