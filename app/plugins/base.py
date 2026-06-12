"""Plugin SDK.

Plugins are discovered through the ``sia.plugins`` entry-point group, so third-party
packages can ship providers by declaring an entry point — no core changes needed:

    [project.entry-points."sia.plugins"]
    my-llm = "my_package.plugin:MyLLMPlugin"

A plugin class exposes identity (``plugin_id``, ``category``), an async lifecycle
(``initialize`` / ``health_check`` / ``shutdown``), and a ``provider`` object
implementing the protocol for its category (see app.providers.base).

Secrets come from the environment (app.config.Settings) — never from the database.
The ``plugins`` table holds only enablement flags and non-secret config.
"""

import logging
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any, Protocol, runtime_checkable

from app.models.enums import PluginCategory

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "sia.plugins"


@dataclass
class PluginHealth:
    healthy: bool
    message: str = ""


class PluginInitError(Exception):
    """Raised by a plugin when it cannot start (e.g. missing credentials)."""


@runtime_checkable
class Plugin(Protocol):
    @property
    def plugin_id(self) -> str: ...

    @property
    def category(self) -> PluginCategory: ...

    @property
    def provider(self) -> Any: ...

    async def initialize(self, config: dict[str, Any]) -> None: ...

    async def health_check(self) -> PluginHealth: ...

    async def shutdown(self) -> None: ...


def discover_plugin_classes() -> dict[str, type]:
    """All plugin classes declared in the sia.plugins entry-point group."""
    classes: dict[str, type] = {}
    for entry_point in entry_points(group=ENTRY_POINT_GROUP):
        try:
            classes[entry_point.name] = entry_point.load()
        except Exception:
            logger.exception("Failed to load plugin entry point %r", entry_point.name)
    return classes


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

    async def initialize_enabled(self, enabled: dict[str, dict[str, Any]]) -> None:
        """Instantiate and initialize every discovered plugin that is enabled.

        ``enabled`` maps plugin_id -> non-secret config (from the plugins table).
        A plugin that fails to initialize is logged and skipped — the system runs
        degraded rather than refusing to boot.
        """
        for name, cls in discover_plugin_classes().items():
            if name not in enabled:
                continue
            plugin = cls()
            try:
                await plugin.initialize(enabled[name])
            except PluginInitError as exc:
                logger.warning("Plugin %r disabled: %s", name, exc)
                continue
            except Exception:
                logger.exception("Plugin %r failed to initialize; skipping", name)
                continue
            self.register(plugin)

    async def health_check_all(self) -> dict[str, PluginHealth]:
        results = {}
        for pid, plugin in self._plugins.items():
            try:
                results[pid] = await plugin.health_check()
            except Exception as e:
                results[pid] = PluginHealth(healthy=False, message=str(e))
        return results

    async def shutdown_all(self) -> None:
        for plugin in self._plugins.values():
            try:
                await plugin.shutdown()
            except Exception:
                logger.exception("Plugin %r failed to shut down", plugin.plugin_id)
