from a2e.core.plugins.interface import (
    A2EPlugin
)


class PluginRegistry:
    def __init__(self):
        self.plugins = {}

    def register(self, plugin: A2EPlugin):
        self.plugins[plugin.name] = plugin

    def get(self, name: str) -> A2EPlugin:
        return self.plugins[name]

    def all(self):
        return list(self.plugins.values())
