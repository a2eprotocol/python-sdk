from a2e.caps.env.plugin import EnvPlugin
from env_registry import EnvRegistry
from counter_env import CounterEnv
from typing import Dict, Any


# ---------------------------------------------------------------------------
# HOST ADAPTER (DISPATCH LAYER)
# ---------------------------------------------------------------------------
class EnvHostAdapter:
    """
    Bridges protocol layer → EnvPlugin instances.
    """
    def __init__(self, registry: EnvRegistry, learning=None):
        self.registry = registry
        self.learning = learning

        # episode_id → env instance
        self._episode_to_env: Dict[str, EnvPlugin] = {}

    # -----------------------------------------------------------------------
    def reset(self, env_name: str, seed=None, options=None):
        env = self.registry.get(env_name)

        episode_id, state = env.reset(seed, options)
        self._episode_to_env[episode_id] = env

        return {
            "episode_id": episode_id,
            "state": state
        }

    # -----------------------------------------------------------------------
    def step(self, episode_id: str, action: Dict[str, Any]):
        env = self._get_env(episode_id)

        prev_state = env.observe()

        next_state, reward, done, info = env.step(action)

        # AUTO LEARNING HOOK
        if self.learning:
            self.learning.record_experience(
                state=prev_state,
                action=action,
                reward=reward,
                next_state=next_state,
                done=done,
                episode_id=episode_id,
            )

        return {
            "next_state": next_state,
            "reward": reward,
            "done": done,
            "info": info
        }

    # -----------------------------------------------------------------------:::::
    def observe(self, episode_id: str):
        env = self._get_env(episode_id)
        return {"state": env.observe(episode_id)}

    # -----------------------------------------------------------------------

    def close(self, episode_id: str):
        env = self._get_env(episode_id)
        env.close()
        self._episode_to_env.pop(episode_id, None)
        return {"closed": True}

    # -----------------------------------------------------------------------

    def spaces(self, env_name: str):
        env = self.registry.get(env_name)
        return env.spaces()

    # -----------------------------------------------------------------------

    def render(self, episode_id: str, mode: str = "text"):
        env = self._get_env(episode_id)
        return {"render": env.render(episode_id, mode)}

    # -----------------------------------------------------------------------

    def _get_env(self, episode_id: str) -> EnvPlugin:
        if episode_id not in self._episode_to_env:
            raise ValueError(f"Unknown episode_id: {episode_id}")
        return self._episode_to_env[episode_id]


# ---------------------------------------------------------------------------
# BOOTSTRAP EXAMPLE
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    registry = EnvRegistry()
    registry.register(CounterEnv())

    host = EnvHostAdapter(registry)

    # simulate usage
    reset = host.reset("counter")
    ep = reset["episode_id"]

    done = False
    while not done:
        step = host.step(ep, {"type": "inc"})
        print(step)
        done = step["done"]

    host.close(ep)
