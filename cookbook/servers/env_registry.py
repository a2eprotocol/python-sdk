from a2e.caps.env.plugin import EnvPlugin
from typing import Dict


# ---------------------------------------------------------------------------
# ENV REGISTRY
# ---------------------------------------------------------------------------
class EnvRegistry:
    def __init__(self):
        self._envs: Dict[str, EnvPlugin] = {}

    def register(self, env: EnvPlugin):
        if env.name in self._envs:
            raise ValueError(f"Env already registered: {env.name}")
        self._envs[env.name] = env

    def get(self, name: str) -> EnvPlugin:
        if name not in self._envs:
            raise ValueError(f"Unknown env: {name}")
        return self._envs[name]
