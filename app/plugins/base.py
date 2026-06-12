from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.models.enums import PluginCategory


@dataclass
class PluginHealth:
    healthy: bool
    message: str = ""


@runtime_checkable
class Plugin(Protocol):
    @property
    def plugin_id(self) -> str: ...

    @property
    def category(self) -> PluginCategory: ...

    async def initialize(self, config: dict[str, Any]) -> None: ...

    async def health_check(self) -> PluginHealth: ...

    async def shutdown(self) -> None: ...


class PluginManager:
    def __init__(self):
        self._plugins: dict[str, Plugin] = {}

    def register(self, plugin: Plugin) -> None:
        self._plugins[plugin.plugin_id] = plugin

    def get(self, plugin_id: str) -> Plugin | None:
        return self._plugins.get(plugin_id)

    def get_by_category(self, category: PluginCategory) -> list[Plugin]:
        return [p for p in self._plugins.values() if p.category == category]

    @property
    def all(self) -> dict[str, Plugin]:
        return dict(self._plugins)

    async def health_check_all(self) -> dict[str, PluginHealth]:
        results = {}
        for pid, plugin in self._plugins.items():
            try:
                results[pid] = await plugin.health_check()
            except Exception as e:
                results[pid] = PluginHealth(healthy=False, message=str(e))
        return results
