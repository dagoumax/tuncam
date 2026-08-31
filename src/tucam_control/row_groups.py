# -*- coding: utf-8 -*-
"""Stable row-group identities kept separate from translated display text."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping


MAX_ROW_GROUPS = 16


@dataclass(frozen=True)
class RowGroupDescriptor:
    key: str
    label: str
    start: int
    end: int


def row_group_key(start: int, end: int) -> str:
    return f"rows:{int(start)}:{int(end)}"


def default_row_group_name(index: int) -> str:
    return f"行组{int(index) + 1}"


def normalize_row_group_names(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    names: dict[str, str] = {}
    for key, name in value.items():
        normalized_key = str(key).strip()
        normalized_name = str(name).strip()
        if (
            normalized_key.startswith("rows:")
            and normalized_name
            and len(normalized_name) <= 32
            and not any(character in normalized_name for character in ("\r", "\n", "\t"))
        ):
            names[normalized_key] = normalized_name
    return names


def describe_row_groups(
    groups: list[tuple[int, int]],
    fallback_height: int | None = None,
    custom_names: Mapping[str, str] | None = None,
) -> list[RowGroupDescriptor]:
    normalized = list(groups)
    if not normalized and fallback_height is not None:
        normalized = [(1, max(1, int(fallback_height)))]
    names = normalize_row_group_names(custom_names)
    descriptors = []
    used_names: set[str] = set()
    for index, (start, end) in enumerate(normalized):
        key = row_group_key(start, end)
        label = names.get(key, default_row_group_name(index))
        if label.casefold() in used_names:
            label = default_row_group_name(index)
        suffix = 2
        base_label = label
        while label.casefold() in used_names:
            label = f"{base_label}-{suffix}"
            suffix += 1
        used_names.add(label.casefold())
        descriptors.append(
            RowGroupDescriptor(
                key=key,
                label=label,
                start=int(start),
                end=int(end),
            )
        )
    return descriptors
