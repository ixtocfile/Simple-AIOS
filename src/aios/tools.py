"""Local tool contracts and registry, independent of the CLI and LLM."""

from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolResult:
    success: bool
    data: dict[str, object] | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool):
            raise TypeError("success must be a boolean")
        if self.success:
            if (
                not isinstance(self.data, dict)
                or any(not isinstance(key, str) for key in self.data)
                or self.error is not None
            ):
                raise ValueError("Success requires a string-keyed data dictionary and no error")
        elif (
            self.data is not None
            or not isinstance(self.error, str)
            or not self.error.strip()
        ):
            raise ValueError("Failure requires a non-empty error and no data")


class Tool(ABC):
    name: str = ""
    description: str = ""

    def execute(self, arguments: dict[str, object]) -> ToolResult:
        """Validate a private copy before running; never expose exception details."""
        if not isinstance(arguments, dict) or any(
            not isinstance(key, str) for key in arguments
        ):
            return ToolResult(success=False, error="Invalid tool arguments")
        try:
            validated = deepcopy(arguments)
            self.validate_arguments(validated)
        except Exception:
            return ToolResult(success=False, error="Invalid tool arguments")

        try:
            result = self._execute(validated)
            if not isinstance(result, ToolResult):
                raise TypeError("Tools must return ToolResult")
        except Exception:
            return ToolResult(success=False, error="Tool execution failed")
        return result

    @abstractmethod
    def validate_arguments(self, arguments: dict[str, object]) -> None:
        """Check required/unknown keys, types and values; raise on invalid input.

        The tool may normalize this private copy for execution.
        """
        raise NotImplementedError

    @abstractmethod
    def _execute(self, arguments: dict[str, object]) -> ToolResult:
        """Run with validated arguments; callers use execute(), not this hook."""
        raise NotImplementedError


class ToolRegistry:
    """Explicit registration and dispatch for trusted Python callers only."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not isinstance(tool, Tool):
            raise TypeError("Only Tool instances can be registered")
        if (
            not isinstance(tool.name, str)
            or not tool.name
            or any(character.isspace() for character in tool.name)
        ):
            raise ValueError("Tool name must be non-empty and contain no whitespace")
        if not isinstance(tool.description, str) or not tool.description.strip():
            raise ValueError("Tool description must be a non-empty string")
        if tool.name in self._tools:
            raise ValueError("Tool name is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        """Return a registered tool, or raise KeyError for an unknown name."""
        return self._tools[name]

    def list_tools(self) -> tuple[Tool, ...]:
        """Return a snapshot in registration order, without executing anything."""
        return tuple(self._tools.values())

    def execute(self, name: str, arguments: dict[str, object]) -> ToolResult:
        if not isinstance(name, str) or name not in self._tools:
            return ToolResult(success=False, error="Unknown tool")
        return self._tools[name].execute(arguments)
