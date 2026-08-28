import importlib.util
from pathlib import Path

import pytest
from app.agent.runtime import SYSTEM_PROMPT

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo_workspace"


def test_demo_workspace_starts_with_a_real_failing_bug():
    spec = importlib.util.spec_from_file_location("m4_demo_calculator", DEMO / "calculator.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.divide(10, 2) == 5
    with pytest.raises(ZeroDivisionError):
        module.divide(10, 0)
    assert "assert divide(10, 0) is None" in (
        DEMO / "test_calculator.py"
    ).read_text(encoding="utf-8")


def test_system_prompt_requires_inspect_edit_verify_and_real_test_success():
    prompt = SYSTEM_PROMPT.casefold()
    assert "inspect, edit, verify" in prompt
    assert "smallest focused change" in prompt
    assert "never modify tests merely to make them pass" in prompt
    assert "exit status" in prompt
    assert "never invent" in prompt
