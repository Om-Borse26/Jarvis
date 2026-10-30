"""
J.A.R.V.I.S. — Extensible Tool Registry & Dynamic Plugin System
Allows any Windows capability, script, or integration to be added,
modified, or removed effortlessly using simple Python decorators.
"""
from __future__ import annotations

import asyncio
import inspect
import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional
from loguru import logger


@dataclass
class ToolParameter:
    name: str
    param_type: str
    description: str
    required: bool = True
    default: Any = None


@dataclass
class ToolDefinition:
    name: str
    description: str
    category: str
    func: Callable
    parameters: list[ToolParameter] = field(default_factory=list)

    def to_schema_str(self) -> str:
        """Produce a clean human-and-LLM-readable schema definition."""
        params_str = ", ".join(
            f"{p.name}: {p.param_type}" + ("" if p.required else f" = {p.default!r}")
            for p in self.parameters
        )
        return f"- {self.name}({params_str}): {self.description}"


class ToolRegistry:
    """Central registry and execution engine for all Jarvis tools."""

    _instance: Optional[ToolRegistry] = None
    _tools: dict[str, ToolDefinition] = {}

    def __new__(cls) -> ToolRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools = {}
        return cls._instance

    def register(
        self,
        func: Callable,
        name: Optional[str] = None,
        description: Optional[str] = None,
        category: str = "general",
    ) -> Callable:
        """Register a function as a callable Jarvis tool."""
        tool_name = name or func.__name__
        doc = description or (func.__doc__ or "").strip().split("\n")[0]
        sig = inspect.signature(func)

        params: list[ToolParameter] = []
        for p_name, param in sig.parameters.items():
            if p_name in ("self", "cls"):
                continue
            if param.annotation != inspect.Parameter.empty:
                if isinstance(param.annotation, str):
                    p_type = param.annotation
                elif hasattr(param.annotation, "__name__"):
                    p_type = param.annotation.__name__
                else:
                    p_type = str(param.annotation)
            else:
                p_type = "str"
            has_default = param.default != inspect.Parameter.empty
            params.append(
                ToolParameter(
                    name=p_name,
                    param_type=p_type,
                    description=p_name,
                    required=not has_default,
                    default=param.default if has_default else None,
                )
            )

        tool_def = ToolDefinition(
            name=tool_name,
            description=doc or f"Execute {tool_name}",
            category=category,
            func=func,
            parameters=params,
        )
        self._tools[tool_name] = tool_def
        logger.debug(f"Tool registered: [{category}] {tool_name}")
        return func

    def unregister(self, tool_name: str) -> bool:
        """Remove a tool dynamically at runtime."""
        if tool_name in self._tools:
            del self._tools[tool_name]
            logger.info(f"Tool unregistered: {tool_name}")
            return True
        return False

    def register_external(
        self,
        name: str,
        description: str,
        category: str,
        parameters: list[ToolParameter],
        func: Callable,
    ) -> None:
        """Register a tool whose schema is supplied explicitly (e.g. an MCP tool)."""
        self._tools[name] = ToolDefinition(
            name=name,
            description=description or f"Execute {name}",
            category=category,
            func=func,
            parameters=parameters or [],
        )
        logger.debug(f"External tool registered: [{category}] {name}")

    def get_tool(self, tool_name: str) -> Optional[ToolDefinition]:
        return self._tools.get(tool_name)

    def list_tools(self, category: Optional[str] = None) -> list[ToolDefinition]:
        """Return all registered tools, optionally filtered by category."""
        if category:
            return [t for t in self._tools.values() if t.category == category]
        return list(self._tools.values())

    async def execute(self, tool_name: str, **kwargs) -> dict[str, Any]:
        """Safely execute a tool by name with arguments."""
        tool = self.get_tool(tool_name)
        if not tool:
            return {"status": "error", "message": f"Tool '{tool_name}' not found in registry."}

        # User-owned permission gate: hard-block disabled tool categories.
        if not self._permitted(tool.category):
            logger.warning(f"🚫 Blocked '{tool_name}': category '{tool.category}' disabled by user.")
            self._audit(tool_name, kwargs, "blocked", "category disabled by user")
            return {
                "status": "error",
                "message": f"I'm not allowed to use {tool.category} tools right now — that access is turned off in your control panel.",
            }

        safe_kwargs = self._redact(kwargs)
        try:
            call_kwargs = self._adapt_kwargs(tool.func, tool_name, kwargs)
            logger.info(f"⚡ Executing tool: {tool_name}({safe_kwargs})")
            if inspect.iscoroutinefunction(tool.func):
                result = await tool.func(**call_kwargs)
            else:
                # Run blocking tools off the event loop so one slow/hung tool
                # can't freeze the whole assistant (audio, hotkey, TTS).
                result = await asyncio.to_thread(tool.func, **call_kwargs)
            self._audit(tool_name, kwargs, "success", str(result))
            return {"status": "success", "result": result}
        except Exception as e:
            logger.error(f"Tool execution failed for '{tool_name}': {e}")
            self._audit(tool_name, kwargs, "error", str(e))
            return {"status": "error", "message": f"Error running {tool_name}: {str(e)}"}

    @staticmethod
    def _adapt_kwargs(func: Callable, tool_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Adapt calling arguments to match the function's actual parameter names."""
        sig = inspect.signature(func)
        params = sig.parameters

        has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())

        COMMON_ALIASES = {
            "percent": ["volume", "brightness", "level", "val", "percentage"],
            "level": ["percent", "volume", "brightness", "val"],
            "text": ["reminder", "message", "task", "note", "content", "query", "reminder_text"],
            "when": ["time", "date", "delay", "at", "after"],
            "filename": ["file_name", "path", "file_path", "name", "target_file"],
            "file_path": ["path", "filename", "file_name", "target_file"],
            "directory": ["dir", "folder", "target_dir", "path"],
            "title_keyword": ["name", "title", "app_name", "app", "window", "keyword"],
            "app_name": ["name", "app", "title", "title_keyword", "application"],
            "hotkey": ["keys", "shortcut", "key"],
            "keys": ["hotkey", "shortcut", "key"],
            "query": ["search", "search_query", "topic", "q"],
            "value": ["secret", "token", "password", "key", "val", "content"],
            "secret": ["value", "token", "password", "key", "val"],
        }

        adapted = dict(kwargs)

        for param_name in params.keys():
            if param_name in adapted:
                continue
            targets = COMMON_ALIASES.get(param_name, [])
            for t in targets:
                if t in adapted:
                    adapted[param_name] = adapted[t]
                    break

        if not has_var_keyword:
            return {k: v for k, v in adapted.items() if k in params}
        return adapted

    @staticmethod
    def _redact(args: dict[str, Any]) -> dict[str, Any]:
        """Mask secret-looking arguments before writing to application logs."""
        try:
            from jarvis.security.audit import redact
            return redact(args)
        except Exception:
            return args

    @staticmethod
    def _permitted(category: str) -> bool:
        """Check the user's permission policy (best-effort; default allow)."""
        try:
            from jarvis.core.permissions import permission_policy
            return permission_policy.is_allowed(category)
        except Exception:
            return True

    @staticmethod
    def _audit(tool_name: str, args: dict, status: str, result: str) -> None:
        """Record the execution in the security audit log (best-effort, never raises)."""
        try:
            from jarvis.security.audit import audit
            audit(tool_name, args, status, result)
        except Exception:
            pass

    def get_prompt_schema(self) -> str:
        """Generate schema formatted for the LLM system prompt."""
        lines = []
        categories: dict[str, list[ToolDefinition]] = {}
        for t in self._tools.values():
            categories.setdefault(t.category, []).append(t)

        for cat, tools in sorted(categories.items()):
            lines.append(f"[{cat.upper()} TOOLS]")
            for t in sorted(tools, key=lambda x: x.name):
                lines.append(t.to_schema_str())
            lines.append("")
        return "\n".join(lines).strip()

    # Python annotation names → JSON Schema types (for native function calling).
    _JSON_TYPE_MAP = {
        "int": "integer", "integer": "integer",
        "float": "number", "number": "number", "double": "number",
        "bool": "boolean", "boolean": "boolean",
        "str": "string", "string": "string",
        "list": "array", "tuple": "array", "sequence": "array",
        "dict": "object", "mapping": "object",
    }

    @classmethod
    def _json_type(cls, py_type: str) -> str:
        """Map a Python type annotation name to a JSON Schema type."""
        base = (py_type or "").strip().lower().replace("typing.", "")
        # Strip optional/union wrappers like "optional[int]" → "int"
        if "[" in base:
            inner = base[base.find("[") + 1 : base.rfind("]")]
            inner = inner.split(",")[0].strip()
            if inner and inner not in ("none",):
                base = inner
        return cls._JSON_TYPE_MAP.get(base, "string")

    def get_tools_schema(
        self,
        categories: Optional[list[str]] = None,
        include_external: Optional[bool] = None,
    ) -> list[dict]:
        """
        Return registered tools in native Ollama/OpenAI function-calling format.

        External MCP tools (category "mcp:<server>") are opt-in: only included when
        include_external is True, or when the scoped categories contain "mcp".
        Tools with "unsafe" in their name are never offered to the model.
        """
        if include_external is None:
            include_external = bool(categories and "mcp" in categories)
        schemas: list[dict] = []
        for t in self._tools.values():
            is_external = t.category.startswith("mcp:")
            if "unsafe" in t.name.lower():
                continue
            if is_external and not include_external:
                continue
            if categories and not is_external and t.category not in categories:
                continue
            properties: dict[str, Any] = {}
            required: list[str] = []
            for p in t.parameters:
                properties[p.name] = {
                    "type": self._json_type(p.param_type),
                    "description": p.description or p.name,
                }
                if p.required:
                    required.append(p.name)
            schemas.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            })
        return schemas

    def auto_discover_plugins(self, plugins_dir: Path | str) -> int:
        """
        Scan a directory and automatically import all .py plugin files.
        Any function decorated with @register_tool in those files is automatically added!
        """
        path = Path(plugins_dir)
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            return 0

        count = 0
        for py_file in path.glob("*.py"):
            if py_file.name.startswith("__"):
                continue
            try:
                mod_name = f"jarvis_plugin_{py_file.stem}"
                spec = importlib.util.spec_from_file_location(mod_name, str(py_file))
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    count += 1
                    logger.info(f"Loaded external plugin: {py_file.name}")
            except Exception as e:
                logger.error(f"Failed to load plugin {py_file.name}: {e}")
        return count


# Global singleton registry
registry = ToolRegistry()


def register_tool(
    name: Optional[str] = None,
    description: Optional[str] = None,
    category: str = "general",
) -> Callable:
    """Decorator to register any Python function into the Jarvis Tool Engine."""
    def decorator(func: Callable) -> Callable:
        registry.register(func, name=name, description=description, category=category)
        return func
    return decorator
