"""Native-traceback frame extraction."""

from __future__ import annotations

from pathlib import Path

from app.runner.trace import parse_exception_message, parse_frames

_NATIVE_TB = """\
Traceback (most recent call last):
  File "/ws/test_calc.py", line 4, in test_divide_by_zero
    assert divide(1, 0) == 0
  File "/ws/calc.py", line 5, in divide
    return a / b
ZeroDivisionError: division by zero
"""


def test_parses_frames_in_source_order() -> None:
    frames = parse_frames(_NATIVE_TB)
    assert [(f.file, f.line, f.function) for f in frames] == [
        ("/ws/test_calc.py", 4, "test_divide_by_zero"),
        ("/ws/calc.py", 5, "divide"),
    ]


def test_innermost_is_last() -> None:
    frames = parse_frames(_NATIVE_TB)
    assert frames[-1].function == "divide"


def test_relativizes_paths_under_workspace(tmp_path: Path) -> None:
    (tmp_path / "calc.py").write_text("x = 1\n", encoding="utf-8")
    tb = f'Traceback (most recent call last):\n  File "{tmp_path / "calc.py"}", line 1, in f\n'
    frames = parse_frames(tb, workspace=tmp_path)
    assert frames[0].file == "calc.py"


def test_leaves_external_paths_absolute(tmp_path: Path) -> None:
    tb = 'Traceback (most recent call last):\n  File "/usr/lib/python3.12/foo.py", line 9, in g\n'
    frames = parse_frames(tb, workspace=tmp_path)
    assert frames[0].file == "/usr/lib/python3.12/foo.py"


def test_extracts_exception_message() -> None:
    assert parse_exception_message(_NATIVE_TB) == "ZeroDivisionError: division by zero"
