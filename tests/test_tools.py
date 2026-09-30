"""Exercise contracts and validation with in-memory tools only."""

from dataclasses import asdict
from unittest.mock import Mock

import pytest

from aios.tools import Tool, ToolRegistry, ToolResult


class EchoTool(Tool):
    name = "test.echo"
    description = "Return a text argument for tests."

    def __init__(self):
        self.calls = []

    def validate_arguments(self, arguments):
        if set(arguments) != {"text"}:
            raise ValueError("Expected only text")
        if not isinstance(arguments["text"], str):
            raise TypeError("text must be a string")
        if not arguments["text"].strip():
            raise ValueError("text must be non-empty")

    def _execute(self, arguments):
        self.calls.append(arguments)
        return ToolResult(success=True, data={"text": arguments["text"]})


def test_tool_requires_validation_and_execution_implementations():
    with pytest.raises(TypeError):
        Tool()

    class MissingValidation(Tool):
        def _execute(self, arguments):
            return ToolResult(success=True, data={})

    with pytest.raises(TypeError):
        MissingValidation()


def test_success_and_failure_results_have_a_consistent_structure():
    assert asdict(ToolResult(success=True, data={"items": [1, 2]})) == {
        "success": True, "data": {"items": [1, 2]}, "error": None,
    }
    assert asdict(ToolResult(success=False, error="Unavailable")) == {
        "success": False, "data": None, "error": "Unavailable",
    }


@pytest.mark.parametrize("values", [
    {"success": True},
    {"success": True, "data": []},
    {"success": True, "data": {1: "value"}},
    {"success": True, "data": {}, "error": "failure"},
    {"success": False},
    {"success": False, "error": " \t"},
    {"success": False, "error": 42},
    {"success": False, "data": {}, "error": "failure"},
])
def test_inconsistent_results_are_rejected(values):
    with pytest.raises(ValueError):
        ToolResult(**values)


def test_result_success_flag_is_a_boolean():
    with pytest.raises(TypeError):
        ToolResult(success=1, data={})


def test_registry_registration_lookup_listing_and_execution():
    registry = ToolRegistry()
    other_registry = ToolRegistry()
    tool = EchoTool()
    assert registry.list_tools() == ()

    registry.register(tool)
    snapshot = registry.list_tools()
    assert snapshot == (tool,)
    assert registry.get("test.echo") is tool
    assert tool.calls == []

    second = EchoTool()
    second.name = "test.second"
    registry.register(second)
    assert registry.list_tools() == (tool, second)
    assert snapshot == (tool,)
    assert other_registry.list_tools() == ()

    result = registry.execute("test.echo", {"text": "Bonjour"})
    assert result == ToolResult(success=True, data={"text": "Bonjour"})
    assert tool.calls == [{"text": "Bonjour"}]
    assert second.calls == []


def test_duplicate_registration_preserves_original_tool():
    registry = ToolRegistry()
    original = EchoTool()
    registry.register(original)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(EchoTool())

    assert registry.get("test.echo") is original
    assert registry.list_tools() == (original,)
    assert original.calls == []


@pytest.mark.parametrize(("attribute", "value"), [
    ("name", ""), ("name", "test echo"), ("name", None),
    ("description", " \t"), ("description", None),
])
def test_invalid_metadata_is_not_registered(attribute, value):
    registry = ToolRegistry()
    tool = EchoTool()
    setattr(tool, attribute, value)

    with pytest.raises(ValueError):
        registry.register(tool)

    assert registry.list_tools() == ()


def test_registry_rejects_objects_that_are_not_tools():
    registry = ToolRegistry()
    with pytest.raises(TypeError):
        registry.register(object())
    assert registry.list_tools() == ()


def test_unknown_tool_does_not_execute_anything():
    registry = ToolRegistry()
    tool = EchoTool()
    registry.register(tool)

    with pytest.raises(KeyError):
        registry.get("test.unknown")
    assert registry.execute("test.unknown", {}) == ToolResult(
        success=False, error="Unknown tool",
    )
    assert registry.execute([], {}) == ToolResult(success=False, error="Unknown tool")
    assert tool.calls == []


@pytest.mark.parametrize("arguments", [
    None, [], [("text", "hello")], {1: "secret"}, {},
    {"text": 42}, {"text": " \t"}, {"text": "hello", "unexpected": True},
])
def test_invalid_arguments_never_reach_execution(arguments):
    registry = ToolRegistry()
    tool = EchoTool()
    registry.register(tool)

    result = registry.execute(tool.name, arguments)

    assert result == ToolResult(success=False, error="Invalid tool arguments")
    assert tool.calls == []


def test_direct_execution_also_validates_arguments():
    tool = EchoTool()
    assert not tool.execute({}).success
    assert tool.calls == []
    assert tool.execute({"text": "ok"}) == ToolResult(success=True, data={"text": "ok"})


def test_validation_and_execution_use_an_independent_copy():
    class NormalizingTool(EchoTool):
        def validate_arguments(self, arguments):
            arguments["nested"]["items"].append("validated")

        def _execute(self, arguments):
            arguments["nested"]["items"].append("executed")
            return ToolResult(success=True, data=arguments)

    original = {"nested": {"items": ["original"]}}

    result = NormalizingTool().execute(original)

    assert result.success
    assert result.data == {"nested": {"items": ["original", "validated", "executed"]}}
    assert original == {"nested": {"items": ["original"]}}


@pytest.mark.parametrize(("hook", "error"), [
    ("validate_arguments", "Invalid tool arguments"),
    ("_execute", "Tool execution failed"),
])
def test_exceptions_produce_safe_failures(monkeypatch, caplog, hook, error):
    tool = EchoTool()
    monkeypatch.setattr(tool, hook, Mock(side_effect=RuntimeError("token=secret-value")))

    result = tool.execute({"text": "private-prompt"})

    assert result == ToolResult(success=False, error=error)
    assert tool.calls == []
    assert not caplog.records


@pytest.mark.parametrize("value", [None, "raw output", {"success": True}])
def test_execution_must_return_a_tool_result(monkeypatch, value):
    tool = EchoTool()
    monkeypatch.setattr(tool, "_execute", Mock(return_value=value))
    assert tool.execute({"text": "hello"}) == ToolResult(
        success=False, error="Tool execution failed",
    )


def test_tool_can_report_an_expected_failure(monkeypatch):
    tool = EchoTool()
    failure = ToolResult(success=False, error="Resource unavailable")
    monkeypatch.setattr(tool, "_execute", Mock(return_value=failure))
    assert tool.execute({"text": "hello"}) is failure


@pytest.mark.parametrize("hook", ["validate_arguments", "_execute"])
@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_control_flow_exceptions_are_not_swallowed(monkeypatch, hook, interruption):
    tool = EchoTool()
    monkeypatch.setattr(tool, hook, Mock(side_effect=interruption))
    with pytest.raises(interruption):
        tool.execute({"text": "hello"})


def test_tool_without_arguments_accepts_only_an_empty_dictionary():
    class NoArgumentsTool(EchoTool):
        def validate_arguments(self, arguments):
            if arguments:
                raise ValueError("No arguments accepted")

        def _execute(self, arguments):
            self.calls.append(arguments)
            return ToolResult(success=True, data={})

    tool = NoArgumentsTool()
    assert tool.execute({}) == ToolResult(success=True, data={})
    assert not tool.execute({"unexpected": True}).success
    assert tool.calls == [{}]
