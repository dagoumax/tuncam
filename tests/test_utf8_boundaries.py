from __future__ import annotations

from pathlib import Path

from tucam_control.row_groups import describe_row_groups


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_project_text_inputs_are_valid_utf8() -> None:
    paths = [
        *PROJECT_ROOT.joinpath("src").rglob("*.py"),
        *PROJECT_ROOT.joinpath("config").glob("*.json"),
        PROJECT_ROOT / "pyproject.toml",
        PROJECT_ROOT / "README.md",
    ]
    for path in paths:
        path.read_text(encoding="utf-8", errors="strict")


def test_row_group_key_does_not_depend_on_display_text() -> None:
    descriptor = describe_row_groups(
        [(10, 20)],
        custom_names={"rows:10:20": "哈龙检测通道"},
    )[0]

    assert descriptor.key == "rows:10:20"
    assert descriptor.label == "哈龙检测通道"
