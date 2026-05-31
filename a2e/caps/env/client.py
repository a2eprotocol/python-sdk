from typing import Callable

from a2e.core.client import A2EClient
from a2e.caps.env import (
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
    ENV_TYPE_MAP,
)
from a2e.caps.env.protocol import MessageType as EnvMessageType

EnvPushCallback = Callable[[EnvStatePush], None]


# ─────────────────────────────────────────────
# Env API
# ─────────────────────────────────────────────
class EnvAPI:
    def __init__(self, client: A2EClient):
        self._c = client
        self._c.update_msg_types(ENV_TYPE_MAP)

        # push callbacks — use the client's push handler registry
        self._env_push_cbs: list[EnvPushCallback] = []
        self._c.register_push_handler(
            EnvMessageType.ENV_STATE_PUSH.value,
            self._on_push,
        )

    def is_done(self, done, truncated) -> bool:
        return done or truncated

    # -----------------------------------------------------
    # RESET (new episode)
    # -----------------------------------------------------
    def reset(
        self,
        env_name: str,
        seed: int | None = None,
        options: dict | None = None,
        timeout: int = 30,
    ) -> EnvResetResponse:
        req = EnvResetRequest(
            env_name=env_name,
            seed=seed,
            options=options or {},
        )

        resp = self._c.rpc(req, timeout=timeout)

        if not isinstance(resp, EnvResetResponse):
            raise ConnectionError(f"Unexpected reset response: {type(resp)}")

        return resp

    # -----------------------------------------------------
    # STEP (act in environment)
    # -----------------------------------------------------
    def step(
        self,
        episode_id: str,
        action: dict,
        timeout: int = 30,
    ) -> EnvStepResponse:
        """
        Executes an action in the environment.

        action = {
            "type": "tool_call",
            "tool": "read_file",
            "args": {...}
        }
        """
        req = EnvStepRequest(episode_id=episode_id, action=action)
        resp = self._c.rpc(req, timeout=timeout)

        if not isinstance(resp, EnvStepResponse):
            raise ConnectionError(f"Unexpected step response: {type(resp)}")

        return resp

    # -----------------------------------------------------
    # OBSERVE (read-only state)
    # -----------------------------------------------------
    def observe(
        self,
        episode_id: str,
        timeout: int = 10,
    ) -> EnvObservation:
        req = EnvObserveRequest(episode_id=episode_id)

        resp = self._c.rpc(req, timeout=timeout)

        if not isinstance(resp, EnvObserveResponse):
            raise ConnectionError(f"Unexpected env observe response: {type(resp)}")

        return EnvObservation.model_validate(resp.obs)

    # -----------------------------------------------------
    # close()
    # -----------------------------------------------------
    def close(
        self,
        episode_id: str,
        timeout: int = 10,
    ) -> EnvObservation:
        req = EnvCloseRequest(episode_id=episode_id)

        resp = self._c.rpc(req, timeout=timeout)

        if not isinstance(resp, EnvCloseResponse):
            raise ConnectionError(f"Unexpected env close response: {type(resp)}")

        return EnvCloseResponse.model_validate(resp)

    # -----------------------------------------------------
    # PUSH (streaming updates)
    # -----------------------------------------------------
    def _on_push(self, msg: EnvStatePush):
        """Internal push handler — dispatches to registered callbacks."""
        for cb in self._env_push_cbs:
            try:
                cb(msg)
            except Exception as exc:
                pass

    def on_push(self, callback: EnvPushCallback):
        """Register callback for EnvStatePush."""
        self._env_push_cbs.append(callback)

    def remove_push_callback(self, callback: EnvPushCallback):
        try:
            self._env_push_cbs.remove(callback)
        except ValueError:
            pass
