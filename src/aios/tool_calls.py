"""Parse a single JSON tool call without authorizing or executing it."""

from dataclasses import dataclass
import json
import math


MAX_TOOL_CALL_LENGTH = 65_536
MAX_TOOL_CALL_DEPTH = 32


class ToolCallError(ValueError):
    """The supplied text does not match the tool-call format."""


@dataclass(frozen=True)
class ToolCall:
    """Decoded content, independent of registry lookup and tool validation."""

    tool: str
    arguments: dict[str, object]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("Invalid JSON number")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number")
    return number


def _check_depth(value: object, depth: int = 1) -> None:
    if not isinstance(value, (dict, list)):
        return
    if depth > MAX_TOOL_CALL_DEPTH:
        raise ValueError("JSON nesting is too deep")
    children = value.values() if isinstance(value, dict) else value
    for child in children:
        _check_depth(child, depth + 1)


def parse_tool_call(text: str) -> ToolCall:
    """Require exactly tool and arguments; never repair or extract partial JSON."""
    if not isinstance(text, str) or len(text) > MAX_TOOL_CALL_LENGTH:
        raise ToolCallError("Invalid tool call")
    try:
        data = json.loads(
            text, object_pairs_hook=_unique_object,
            parse_constant=_reject_constant, parse_float=_finite_float,
        )
        if not isinstance(data, dict) or data.keys() != {"tool", "arguments"}:
            raise ValueError("Expected tool and arguments")
        name = data["tool"]
        if (
            not isinstance(name, str) or not name or not name.isprintable()
            or any(character.isspace() for character in name)
        ):
            raise ValueError("Invalid tool name")
        if not isinstance(data["arguments"], dict):
            raise ValueError("Arguments must be a JSON object")
        _check_depth(data)
    except (ValueError, RecursionError):
        raise ToolCallError("Invalid tool call") from None
    return ToolCall(tool=name, arguments=data["arguments"])
