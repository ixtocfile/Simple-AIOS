"""Check that the prompt documents the actual tool and call contracts."""

import re
from unittest.mock import Mock

from aios.core import MAX_TOOL_CALLS_PER_REQUEST, build_tool_registry
from aios.system_prompt import SYSTEM_PROMPT
from aios.tool_calls import parse_tool_call


def test_catalogue_matches_registered_names_and_risks_and_has_valid_examples(monkeypatch):
    registry = build_tool_registry()
    declarations = re.findall(r"^- ([\w.]+) \[(READ|CONFIRM|DENY)\]", SYSTEM_PROMPT, re.MULTILINE)
    assert declarations == [(tool.name, tool.risk_level.name) for tool in registry.list_tools()]
    examples = [parse_tool_call(line) for line in SYSTEM_PROMPT.splitlines() if line.startswith("{")]
    assert [call.tool for call in examples] == [tool.name for tool in registry.list_tools()]
    blocked = Mock(side_effect=AssertionError("Documented examples must not execute"))
    for tool in registry.list_tools():
        monkeypatch.setattr(tool, "execute", blocked)
        monkeypatch.setattr(tool, "_execute", blocked)

    for call in examples:
        registry.get(call.tool).validate_arguments(call.arguments.copy())

    blocked.assert_not_called()


def test_documented_call_budget_matches_the_cli_limit():
    budget = re.search(r"La limite est de (\d+) tentatives d'appels", SYSTEM_PROMPT)
    assert budget is not None
    assert int(budget.group(1)) == MAX_TOOL_CALLS_PER_REQUEST
