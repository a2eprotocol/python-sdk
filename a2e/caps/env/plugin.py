# ═════════════════════════════════════════════════════════════════════════════
# A2E EnvPlugin System — Single File Implementation
# ═════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pdb
import time
import copy
from pydantic import BaseModel
from typing import (
    Dict, Any, Optional,
    List, Callable, Type
)

from a2e.caps.env.store import (
    EpisodeStore
)

from a2e.caps.env.protocol import (
    EnvStatePush,
    _Episode,
    EnvResetRequest,
    EnvResetResponse,
    EnvStepRequest,
    EnvStepResponse,
    EnvObserveRequest,
    EnvObserveResponse,
    EnvCloseRequest,
    EnvCloseResponse,
    EnvErrorCode,
    EnvObservation,
    EnvAction,
    EnvState,
    DEFAULT_DATA_ROOT,
    EnvDataAddRequest,
    EnvDataAddResponse,
    EnvDataGetRequest,
    EnvDataGetResponse,
    EnvDataResetRequest,
    EnvDataResetResponse,
    ENV_TYPE_MAP
)

from a2e.caps.base.protocol import (
    A2EErrorCode,
    A2EError,
    A2EMessage,
)
from a2e.core.plugins import (
    A2EPlugin
)


# ---------------------------------------------------------------------------
# BASE ENV PLUGIN
# ---------------------------------------------------------------------------
class EnvPlugin(A2EPlugin):
    """
    Base class for all A2E environments.

    Each environment maintains multiple concurrent episodes.
    """
    name: str = "base_env"

    def __init__(self, host_instance, config):
        super().setup(host_instance, config)

        # Setup persistent store, if configured
        self._store: Optional[EpisodeStore] = config.get("store")

        # Stores current state
        self._episode: Optional[_Episode] = None

        # Used to store previous/all step state
        self.steps = {}

        self._active = False

        # For events
        self._push_cb: Optional[Callable[[EnvStatePush], None]] = None

    # -----------------------------------------------------------------------
    # LIFECYCLE
    # -----------------------------------------------------------------------
    def on_reset(
        self,
        seed: Optional[int],
        options: Dict[str, Any]
    ) -> EnvState:
        raise NotImplementedError

    def on_step(self, episode_id: str, action: EnvAction):
        """
        Must return: (next_state, reward, done, info)
        """
        raise NotImplementedError

    def on_close(self):
        """
        Optional cleanup hook.
        """
        pass

    # ------------------------------------------------------------------
    # DATA PLANE (optional)
    #
    # Deliberately separate from on_reset: these move data into and out of
    # the env's data root (default /workspace/data) and are orthogonal to the
    # episode lifecycle. Defaults are no-ops (NOT NotImplementedError) so an
    # existing EnvPlugin subclass keeps working unchanged until it opts in.
    # ------------------------------------------------------------------
    def on_data_reset(self, scope: str = "all",
                      data_root: str = DEFAULT_DATA_ROOT) -> Dict[str, Any]:
        """Restore the data plane to its pristine state.

        NOT a purge-to-empty and NOT an episode reset. A host with no baseline
        corpus simply empties the root. Return ``{"restored": <int>, ...}``.
        """
        return {"restored": 0, "data_root": data_root}

    def on_data_add(self, parts: List[Dict[str, Any]],
                    data_root: str = DEFAULT_DATA_ROOT) -> Dict[str, Any]:
        """Stage task data into the data root. Bytes are moved on the host's
        filesystem, never through the protocol. Return ``{"added": <int>,
        "errors": [...], "staged": [...]}``."""
        return {"added": 0, "errors": [], "staged": [], "data_root": data_root}

    def on_data_get(self, query: str = "", include_content: bool = False,
                    max_bytes: int = 1_048_576,
                    data_root: str = DEFAULT_DATA_ROOT) -> List[Dict[str, Any]]:
        """Read items back out of the data root (graded artifact collection)."""
        return []

    def reset(
        self,
        seed: Optional[int] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> EnvObservation:
        options = options or {}

        if self._episode:
            self.close()

        self.steps = {}

        state = self.on_reset(seed=seed, options=options or {})

        self._episode = _Episode(
            state=state or {},
            done=False,
            step_num=0,
            created=time.time()
        )
        self.steps[0] = copy.deepcopy(self._episode)

        self._persist()
        return EnvObservation(**{
            "episode_id": self._episode.id,
            "step_num": 0,
            "state": state,
            "done": False,
            "truncated": False,
        })

    def close(self) -> None:
        if not self._episode:
            return

        if self._store and self._episode:
            try:
                self._store.delete(self._episode.id)
            except Exception as error:
                print(
                    "Unable to delete from store:"
                    f"{self._episode_id}, {str(error)}"
                )
                pass
        try:
            self.on_close()
        except Exception as error:
            print(f"Unable to close the connection: {str(error)}")
            pass

        self._episode = None

    def step(self, action: EnvAction) -> EnvObservation:
        """
        Apply action → returns next_state, reward, done, info
        """
        ep = self._require_episode()

        if ep.done:
            raise RuntimeError("Episode already completed. Call reset().")

        obs = self.on_step(ep.id, action)

        ep.state = obs.state or {}
        ep.done = bool(obs.done)
        ep.step_num += 1

        self.steps[ep.step_num] = copy.deepcopy(ep)

        self._persist()

        return obs

    def observe(self) -> EnvObservation:
        """
        Return current state snapshot.
        """
        ep = self._require_episode()

        return EnvObservation(**{
            "episode_id": self._episode.id,
            "step_num": ep.step_num,
            "state": ep.state,
            "done": ep.done,
            "created_at": ep.created_at,
        })

    # -----------------------------------------------------------------------
    # METADATA
    # -----------------------------------------------------------------------
    def spaces(self) -> Dict[str, Any]:
        return {
            "action_space": {},
            "state_schema": {},
        }

    def render(self, mode: str = "text") -> Any:
        ep = self._require_episode()

        if mode == "text":
            return str(ep.state)

        if mode == "json":
            return ep.state

        return None

    def plan(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        return []

    # -----------------------------------------------------------------------
    # PUSH SUPPORT
    # -----------------------------------------------------------------------
    def set_push_callback(self, fn: Callable[[Any], None]):
        self._push_cb = fn

    def push(
        self,
        event_type: str,
        delta: dict | None = None,
        *,
        action_id: str | None = None,
        reward: float | None = None,
        reward_info: dict | None = None,
        terminal: bool = False,
        done_reason: str | None = None,
        reason: str = ""
    ):
        """Helper to emit a structured EnvStatePush event."""

        if not self._episode:
            return

        msg = EnvStatePush(
            episode_id=self._episode.id,
            step_id=self._episode.step_num,
            action_id=action_id,
            event_type=event_type,
            delta=delta or {},
            reward=reward,
            reward_info=reward_info or {},
            terminal=terminal,
            done_reason=done_reason,
            reason=reason,
        )

        if not self._push_cb:
            return

        # --- emit safely ---
        try:
            self._push_cb(msg)
        except Exception as e:
            # do NOT silently swallow
            # but also don't crash env execution
            print(f"[Env.push] callback failed: {e}")

    # ---------------------------------------------------------------------
    # INTERNAL
    # ---------------------------------------------------------------------
    def _require_episode(self) -> _Episode:
        if not self._episode:
            self._load_if_needed()

        if not self._episode:
            raise RuntimeError("No active episode. Call reset().")

        return self._episode

    def _persist(self):
        if not self._store or not self._episode:
            return

        try:
            self._store.save(self._episode.id, {
                "state": self._episode.state,
                "done": self._episode.done,
                "step_num": self._episode.step_num,
                "created_at": self._episode.created_at,
            })
        except Exception:
            pass

    def _load_if_needed(self):
        if self._episode or not self._store:
            return

        try:
            data = self._store.load(self._episode.id)
            if data:
                self._episode = _Episode(
                    state=data["state"],
                    done=data["done"],
                    step_num=data["step_num"],
                    created_at=data["created_at"],
                )
        except Exception:
            pass

    # ---------------------------------------------------------------------
    # Protocol handler
    # ---------------------------------------------------------------------
    def supported_messages(self) -> Dict[str, Type[BaseModel]]:
        return ENV_TYPE_MAP

    def handle(self, msg: A2EMessage) -> A2EMessage:
        """
        Returns True if message was handled here.
        """
        response = None
        req_id = msg.id
        t0 = time.monotonic()

        # ─────────────────────────────
        # EnvStepRequest
        # ─────────────────────────────
        if isinstance(msg, EnvStepRequest):
            try:
                obs = self.step(msg.action)
                response = EnvStepResponse(**{
                    "req_id": req_id,
                    "obs": obs
                })
            except Exception as error:
                response = A2EError(**{
                    "req_id": req_id,
                    "code": EnvErrorCode.RUNTIME_ERROR,
                    "message": str(error),
                    "retryable": False
                })
            finally:
                self.audit_handle(msg, response, req_id, t0)
                return response

        # ─────────────────────────────
        # Env Observation
        # ─────────────────────────────
        if isinstance(msg, EnvObserveRequest):
            try:
                observation = self.observe()
                response = EnvObserveResponse(
                    req_id=req_id,
                    obs=observation
                )
            except Exception as error:
                # NOTE: use the outer req_id (== msg.id). Previously this did
                # `req_id = msg.get("id", "")`, which raises AttributeError on
                # pydantic models; the `finally: return response` then swallowed
                # the in-flight exception and returned the stale response=None,
                # so no reply was ever sent → client-side silent RPC hang.
                response = A2EError(**{
                    "req_id": req_id,
                    "code": EnvErrorCode.RUNTIME_ERROR,
                    "message": str(error),
                    "retryable": False
                })
            finally:
                self.audit_handle(msg, response, req_id, t0)
                return response

        # ─────────────────────────────
        # Env Reset
        # ─────────────────────────────
        if isinstance(msg, EnvResetRequest):
            try:
                obs = self.reset(msg.seed, msg.options)
                response = EnvResetResponse(**{
                    "req_id": req_id,
                    "obs": obs
                })
            except Exception as error:
                # NOTE: use the outer req_id (== msg.id). Previously this did
                # `req_id = msg.get("id", "")`, which raises AttributeError on
                # pydantic models; the `finally: return response` then swallowed
                # the in-flight exception and returned the stale response=None,
                # so no reply was ever sent → client-side silent RPC hang.
                response = A2EError(**{
                    "req_id": req_id,
                    "code": EnvErrorCode.RUNTIME_ERROR,
                    "message": str(error),
                    "retryable": False
                })
            finally:
                self.audit_handle(msg, response, req_id, t0)
                return response

        # ─────────────────────────────
        # Env Close
        # ─────────────────────────────
        if isinstance(msg, EnvCloseRequest):
            try:
                self.close()
                response = EnvCloseResponse(**{
                    "req_id": req_id,
                    "closed": True
                })
            except Exception as error:
                response = A2EError(**{
                    "req_id": req_id,
                    "code": EnvErrorCode.RUNTIME_ERROR,
                    "message": str(error),
                    "retryable": False
                })
            finally:
                self.audit_handle(msg, response, req_id, t0)
                return response

        # ─────────────────────────────
        # Data plane — task-data lifecycle, orthogonal to env/reset above
        # ─────────────────────────────
        if isinstance(msg, EnvDataResetRequest):
            try:
                result = self.on_data_reset(
                    scope=msg.scope,
                    data_root=msg.data_root or DEFAULT_DATA_ROOT,
                ) or {}
                response = EnvDataResetResponse(**{
                    "req_id": req_id,
                    "ok": True,
                    "restored": int(result.get("restored", 0)),
                    "data_root": result.get("data_root", msg.data_root),
                    "detail": str(result.get("detail", "")),
                })
            except Exception as error:
                response = A2EError(**{
                    "req_id": req_id,
                    "code": EnvErrorCode.RUNTIME_ERROR,
                    "message": str(error),
                    "retryable": False
                })
            finally:
                self.audit_handle(msg, response, req_id, t0)
            return response

        if isinstance(msg, EnvDataAddRequest):
            try:
                parts = [p.model_dump() if hasattr(p, "model_dump") else dict(p)
                         for p in (msg.parts or [])]
                result = self.on_data_add(
                    parts=parts,
                    data_root=msg.data_root or DEFAULT_DATA_ROOT,
                ) or {}
                errors = list(result.get("errors", []) or [])
                response = EnvDataAddResponse(**{
                    "req_id": req_id,
                    "ok": not errors,
                    "added": int(result.get("added", 0)),
                    "errors": errors,
                    # model_dump the staged entries: the executor re-validates
                    # the response on serialization (G3).
                    "staged": list(result.get("staged", []) or []),
                })
            except Exception as error:
                response = A2EError(**{
                    "req_id": req_id,
                    "code": EnvErrorCode.RUNTIME_ERROR,
                    "message": str(error),
                    "retryable": False
                })
            finally:
                self.audit_handle(msg, response, req_id, t0)
            return response

        if isinstance(msg, EnvDataGetRequest):
            try:
                items = self.on_data_get(
                    query=msg.query or "",
                    include_content=bool(msg.include_content),
                    max_bytes=int(msg.max_bytes),
                    data_root=msg.data_root or DEFAULT_DATA_ROOT,
                ) or []
                response = EnvDataGetResponse(**{
                    "req_id": req_id,
                    "ok": True,
                    "items": list(items),
                    "truncated": bool(msg.include_content and any(
                        len(str(i.get("content", ""))) >= int(msg.max_bytes)
                        for i in items if isinstance(i, dict)
                    )),
                })
            except Exception as error:
                response = A2EError(**{
                    "req_id": req_id,
                    "code": EnvErrorCode.RUNTIME_ERROR,
                    "message": str(error),
                    "retryable": False
                })
            finally:
                self.audit_handle(msg, response, req_id, t0)
            return response

        # Return invalid message
        response = A2EError(**{
            "req_id": req_id,
            "code": A2EErrorCode.INVALID_MESSAGE,
            "message": f"Invalid message: {msg.type}",
            "retryable": False
        })
        self.audit_handle(msg, response, req_id, t0)
        return response
