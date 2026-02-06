"""Plugin discovery and registration."""

from __future__ import annotations

from typing import Dict, Type

from .base import NexusPlugin, BasePlugin

# Registry populated at runtime by PluginManager
registered_plugins: Dict[str, NexusPlugin] = {}


def discover_plugins() -> Dict[str, Type[NexusPlugin]]:
    """Load plugins that expose the ``nexus.plugins`` entry-point.

    Falls back gracefully if no entry-points are installed.
    """
    plugins: Dict[str, Type[NexusPlugin]] = {}
    try:
        from importlib.metadata import entry_points
        eps = entry_points()
        nexus_eps = eps.get("nexus.plugins", []) if isinstance(eps, dict) else eps.select(group="nexus.plugins")
        for ep in nexus_eps:
            plugin_cls = ep.load()
            if issubclass(plugin_cls, NexusPlugin):
                plugins[ep.name] = plugin_cls
    except Exception:
        pass
    return plugins
