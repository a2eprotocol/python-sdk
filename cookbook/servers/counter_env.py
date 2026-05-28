import pdb
from typing import Dict, Any
from a2e.caps.env.plugin import EnvPlugin
from a2e.caps.env.protocol import EnvState, EnvObservation


class CounterEnv(EnvPlugin):
    name = "counter"

    # ------------------------------------------------------------------
    # RESET
    # ------------------------------------------------------------------
    def on_reset(self, seed=None, options=None) -> EnvState:
        self.state = EnvState(**{"count": 0, "step_num": 0})
        return self.state

    # ------------------------------------------------------------------
    # STEP
    # ------------------------------------------------------------------
    def on_step(self, episode_id: str, action: Dict[str, Any]) -> EnvObservation:
        # ensure state exists
        if not hasattr(self, "state"):
            raise RuntimeError("Env not reset. Call env/reset first.")

        if action.get("type") == "inc":
            self.state.count += 1

        reward = 1.0 if self.state.count == 5 else 0.0
        done = self.state.count >= 5
        truncated = False
        return EnvObservation(**{
            "episode_id": episode_id,
            "step_num": self.state.step_num,
            "state": self.state,
            "reward": reward,
            "done": done,
            "truncated": truncated,
            "info": {}
        })
