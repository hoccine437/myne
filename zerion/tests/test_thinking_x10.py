"""Verification for Zerion's bounded Think x10 quality protocol."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest import mock

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.chdir(BASE)

import config  # noqa: E402


def test_x10_defaults_to_ten_lenses_without_provider_fanout():
    from cognition.deep_thinking import build_brief

    brief = build_brief(
        "compare two safe approaches",
        SimpleNamespace(mode=SimpleNamespace(name="decision_analysis")),
        SimpleNamespace(strategy="evidence-led", confidence=.8),
        "[knowledge/note] verified fact",
        [{"content": "validated method"}],
        SimpleNamespace(intent=SimpleNamespace(value="chat"),
                        needs_execution=False, needs_planning=False),
    )
    assert config.THINKING_MODE == "x10"
    assert config.THINKING_MULTIPLIER == 10
    assert brief.enabled
    assert len(brief.lenses) == 10
    assert "Do not reveal chain-of-thought" in brief.prompt_block()
    assert brief.telemetry()["lenses"] == 10


def test_x10_expands_bounded_context_and_history_budgets():
    assert config.thinking_context_budget() == 60000
    assert config.thinking_history_limit() == 50
    assert config.thinking_knowledge_limit() == 50
    assert config.thinking_plan_max_tasks() == 10


def test_off_mode_restores_lightweight_allowances():
    old_mode, old_multiplier = config.THINKING_MODE, config.THINKING_MULTIPLIER
    try:
        config.THINKING_MODE = "off"
        config.THINKING_MULTIPLIER = 10
        assert not config.thinking_enabled()
        assert config.thinking_context_budget() == 6000
        assert config.thinking_history_limit() == config.MAX_HISTORY
        assert config.thinking_knowledge_limit() == 5
        assert config.thinking_plan_max_tasks() == 5
    finally:
        config.THINKING_MODE, config.THINKING_MULTIPLIER = old_mode, old_multiplier


def test_planner_receives_depth_context_and_evidence_contract():
    from planner.decomposer import decompose

    with mock.patch("planner.decomposer.api.call_llm", return_value='{"complex": false}') as call:
        plan = decompose(
            "research Zerion then save a summary",
            [{"name": "write_file", "description": "write a file"}],
            reasoning_context={"deep_thinking_protocol": "ten lenses"},
            recent_history="User: previous request",
        )
    assert plan.is_simple()
    prompt = call.call_args.args[1]
    assert "ten lenses" in prompt
    assert "previous request" in prompt
    assert "2 to 10 tasks" in prompt
    assert "expected_result" in prompt


def test_plan_task_serializes_expected_evidence():
    from planner.models import Task

    task = Task(1, "check", "calculate", expected_result="42")
    assert task.to_dict()["expected_result"] == "42"
