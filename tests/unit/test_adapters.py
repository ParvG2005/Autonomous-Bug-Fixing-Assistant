"""Adapter registry: detection, lookup, and cross-language frame parsing."""

from __future__ import annotations

from pathlib import Path

from app.runner.adapters import (
    GoTestAdapter,
    NodeTestAdapter,
    PytestAdapter,
    adapter_for,
    detect_adapter,
    parse_any_frames,
)
from app.runner.models import Framework


def test_detects_python(failing_project: Path) -> None:
    adapter = detect_adapter(failing_project)
    assert isinstance(adapter, PytestAdapter)
    assert adapter.framework is Framework.PYTEST


def test_detects_node_from_package_json(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "x"}\n', encoding="utf-8")
    assert isinstance(detect_adapter(tmp_path), NodeTestAdapter)


def test_detects_node_from_test_file(tmp_path: Path) -> None:
    (tmp_path / "calc.test.js").write_text("// test\n", encoding="utf-8")
    assert isinstance(detect_adapter(tmp_path), NodeTestAdapter)


def test_detects_go_from_go_mod(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module example/x\n\ngo 1.23\n", encoding="utf-8")
    assert isinstance(detect_adapter(tmp_path), GoTestAdapter)


def test_detects_go_from_test_file(tmp_path: Path) -> None:
    (tmp_path / "calc_test.go").write_text("package calc\n", encoding="utf-8")
    assert isinstance(detect_adapter(tmp_path), GoTestAdapter)


def test_no_adapter_for_empty_workspace(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
    assert detect_adapter(tmp_path) is None


def test_python_wins_over_node_when_both_present(tmp_path: Path) -> None:
    # A Python repo that happens to vendor a JS test file still resolves to pytest
    # (registry order: Python first).
    (tmp_path / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    (tmp_path / "thing.test.js").write_text("// test\n", encoding="utf-8")
    assert isinstance(detect_adapter(tmp_path), PytestAdapter)


def test_adapter_for_round_trips() -> None:
    for fw in (Framework.PYTEST, Framework.NODE_TEST, Framework.GO_TEST):
        assert adapter_for(fw).framework is fw


def test_each_adapter_declares_image_and_commands() -> None:
    for fw in (Framework.PYTEST, Framework.NODE_TEST, Framework.GO_TEST):
        adapter = adapter_for(fw)
        assert adapter.image.startswith("bugfix-sandbox-")
        assert adapter.commands  # non-empty


def test_parse_any_frames_python_traceback() -> None:
    text = (
        "Traceback (most recent call last):\n"
        '  File "calc.py", line 5, in divide\n'
        "    return a / b\n"
        "ZeroDivisionError: division by zero\n"
    )
    frames = parse_any_frames(text)
    assert frames and frames[-1].file == "calc.py"


def test_parse_any_frames_node_stack() -> None:
    text = "    at divide (/workspace/calc.js:3:10)\n"
    frames = parse_any_frames(text, "/workspace")
    assert frames and frames[-1].file == "calc.js"
    assert frames[-1].function == "divide"


def test_parse_any_frames_go_stack() -> None:
    text = "    calc_test.go:12: Divide(1, 0) = +Inf; want error\n"
    frames = parse_any_frames(text)
    assert frames and frames[-1].file == "calc_test.go"
    assert frames[-1].line == 12
