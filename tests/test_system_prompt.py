"""Check that the prompt documents the actual tool and call contracts."""

import json
import re
from unittest.mock import Mock

from aios.core import MAX_TOOL_CALLS_PER_REQUEST, build_tool_registry
from aios.system_prompt import SYSTEM_PROMPT, build_system_prompt
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


def test_prompt_exposes_effective_roots_as_json_data_and_examples_remain_valid(tmp_path):
    roots = (tmp_path / 'dossier "cité"', tmp_path / "second")
    prompt = build_system_prompt(roots)
    assert prompt.startswith(SYSTEM_PROMPT)
    assert json.loads(prompt.split("filesystem_roots effectifs (JSON) : ")[1]) == [str(root) for root in roots]
    registry = build_tool_registry(filesystem_roots=roots)
    for line in prompt.splitlines():
        if line.startswith("{"):
            call = parse_tool_call(line)
            registry.get(call.tool).validate_arguments(call.arguments)
            if call.tool.startswith("filesystem."):
                assert call.arguments["workspace"] == str(roots[0])


def test_prompt_distinguishes_default_roots_from_disabled_filesystem():
    assert build_system_prompt() == SYSTEM_PROMPT
    disabled = build_system_prompt(())
    assert disabled.endswith("filesystem_roots effectifs (JSON) : []\n")
