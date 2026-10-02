"""Check explicit terminal consent, with no real tools or LLM calls."""

from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from aios.__main__ import authorize_tool_call
from aios.policy import PolicyDecision, PolicyEngine
from aios.tools import RiskLevel, Tool, ToolRegistry


class ConfirmationTool(Tool):
    name = "test.action"
    description = "A fictitious action requiring explicit consent."
    risk_level = RiskLevel.CONFIRM

    def validate_arguments(self, arguments):
        raise AssertionError("Confirmation must not validate tool arguments")

    def _execute(self, arguments):
        raise AssertionError("Confirmation must not execute the tool")


@pytest.fixture
def confirmation(monkeypatch):
    registry = ToolRegistry()
    tool = ConfirmationTool()
    registry.register(tool)
    blocked = Mock(side_effect=AssertionError("Unexpected execution or LLM call"))
    for method in ("execute", "validate_arguments", "_execute"):
        monkeypatch.setattr(tool, method, blocked)
    monkeypatch.setattr(registry, "execute", blocked)
    monkeypatch.setattr("aios.__main__.OllamaProvider", blocked)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    reader = Mock(return_value="")
    monkeypatch.setattr("builtins.input", reader)
    yield PolicyEngine(registry), tool, reader
    blocked.assert_not_called()


@pytest.mark.parametrize("answer", ["oui", "OUI", "  Oui\t"])
def test_only_explicit_yes_authorizes_the_presented_action(confirmation, answer, capsys, caplog):
    policy, tool, reader = confirmation
    reader.return_value = answer
    arguments = {"target": "demo", "options": {"mode": "safe"}}
    original = deepcopy(arguments)

    assert authorize_tool_call(policy.evaluate(tool.name), tool.name, arguments) is True

    captured = capsys.readouterr()
    preview = captured.out.removeprefix("Action à confirmer : ").strip()
    assert json.loads(preview) == {"outil": tool.name, "arguments": arguments}
    assert arguments == original
    assert captured.err == ""
    reader.assert_called_once_with("Confirmer cette action ? Tapez oui [oui/NON] : ")
    assert not caplog.records


@pytest.mark.parametrize("answer", [
    "", " \t", "non", "NON", "n", "o", "yes", "y", "true", "oui non",
    "/exit", '{"confirmed": true}',
])
def test_empty_negative_or_ambiguous_answer_is_refused(confirmation, answer, capsys, caplog):
    policy, tool, reader = confirmation
    reader.return_value = answer

    assert authorize_tool_call(policy.evaluate(tool.name), tool.name, {}) is False

    assert capsys.readouterr().out.endswith("Action refusée.\n")
    reader.assert_called_once()
    assert not caplog.records


@pytest.mark.parametrize("error", [
    EOFError(), KeyboardInterrupt(), OSError("private input error"),
])
def test_interrupted_or_unreadable_confirmation_is_refused(confirmation, error, capsys, caplog):
    policy, tool, reader = confirmation
    reader.side_effect = error

    assert authorize_tool_call(policy.evaluate(tool.name), tool.name, {}) is False

    captured = capsys.readouterr()
    assert captured.out.endswith("Action refusée.\n")
    assert "private input error" not in captured.out + captured.err
    assert not caplog.records


def test_non_interactive_input_cannot_grant_confirmation(confirmation, monkeypatch, capsys):
    policy, tool, reader = confirmation
    reader.return_value = "oui"
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    assert authorize_tool_call(policy.evaluate(tool.name), tool.name, {"target": "private-target"}) is False

    reader.assert_not_called()
    captured = capsys.readouterr()
    assert "terminal interactif requis" in captured.out
    assert captured.out.endswith("Action refusée.\n")
    assert "private-target" not in captured.out


@pytest.mark.parametrize(("risk_level", "expected"), [
    (RiskLevel.READ, True), (RiskLevel.DENY, False),
])
def test_policy_allow_and_deny_do_not_prompt(confirmation, risk_level, expected):
    policy, tool, reader = confirmation
    tool.risk_level = risk_level
    reader.return_value = "oui"

    assert authorize_tool_call(policy.evaluate(tool.name), tool.name, {}) is expected
    reader.assert_not_called()


def test_unknown_tool_cannot_be_confirmed(confirmation):
    policy, _, reader = confirmation
    reader.return_value = "oui"

    assert authorize_tool_call(policy.evaluate("test.unknown"), "test.unknown", {}) is False
    reader.assert_not_called()


@pytest.mark.parametrize("decision", [None, "ALLOW", "CONFIRM", True])
def test_unexpected_policy_decision_is_refused(confirmation, monkeypatch, decision):
    policy, tool, reader = confirmation
    monkeypatch.setattr(policy, "evaluate", lambda _: decision)

    assert authorize_tool_call(policy.evaluate(tool.name), tool.name, {}) is False
    reader.assert_not_called()


def test_consent_is_never_reused_and_policy_is_rechecked(confirmation):
    policy, tool, reader = confirmation
    reader.side_effect = ["oui", ""]

    assert authorize_tool_call(policy.evaluate(tool.name), tool.name, {"target": "first"}) is True
    assert authorize_tool_call(policy.evaluate(tool.name), tool.name, {"target": "second"}) is False
    assert reader.call_count == 2
    assert policy.evaluate(tool.name) is PolicyDecision.CONFIRM

    tool.risk_level = RiskLevel.DENY
    assert authorize_tool_call(policy.evaluate(tool.name), tool.name, {"target": "first"}) is False
    assert reader.call_count == 2


def test_preview_escapes_terminal_controls_without_logging_arguments(confirmation, capsys, caplog):
    policy, tool, reader = confirmation
    arguments = {"target": "secret-target\n\x1b[2J\r\u202e", "confirmed": True}
    reader.return_value = ""

    assert authorize_tool_call(policy.evaluate(tool.name), tool.name, arguments) is False

    captured = capsys.readouterr()
    preview = captured.out.splitlines()[0].removeprefix("Action à confirmer : ")
    assert json.loads(preview)["arguments"] == arguments
    assert "\x1b" not in captured.out
    assert "\r" not in captured.out
    assert "\u202e" not in captured.out
    assert not caplog.records


@pytest.mark.parametrize("arguments", [
    None, [], {1: "value"}, {"value": object()}, {"value": float("nan")},
])
def test_unrepresentable_action_is_refused_without_prompt(confirmation, arguments, capsys):
    policy, tool, reader = confirmation

    assert authorize_tool_call(policy.evaluate(tool.name), tool.name, arguments) is False

    reader.assert_not_called()
    captured = capsys.readouterr()
    assert captured.out == "Action refusée.\n"
    assert captured.err == ""
