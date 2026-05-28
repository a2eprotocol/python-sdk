from a2e.core.plugins.interface import (
    A2EPlugin
)


class CapabilityRegistry:
    def __init__(self):
        self._capabilities = {}

    def register(self, capability: str, plugin: A2EPlugin):
        self._capabilities.setdefault(capability, []).append(plugin)

    def get(self, capability: str):
        return self._capabilities.get(capability, [])
