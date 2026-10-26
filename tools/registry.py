"""
WorkGraph Tool Registry
Manages typed ToolSpecs, permissions, risk levels, and dispatch.
"""

from typing import Dict, Any, Callable, Optional, List
from runtime.contracts import ToolSpec, RiskLevel

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolSpec] = {}
        self._handlers: Dict[str, Callable] = {}

    def register(self, tool_spec: ToolSpec, handler: Callable):
        self._tools[tool_spec.name] = tool_spec
        self._handlers[tool_spec.name] = handler

    def get_spec(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def get_handler(self, name: str) -> Optional[Callable]:
        return self._handlers.get(name)

    def list_specs(self) -> List[ToolSpec]:
        return list(self._tools.values())

    def execute(self, name: str, args: Dict[str, Any]) -> Any:
        handler = self.get_handler(name)
        if not handler:
            raise ValueError(f"Tool '{name}' is not registered in ToolRegistry.")
        return handler(**args)


# Global default registry instance
global_registry = ToolRegistry()
