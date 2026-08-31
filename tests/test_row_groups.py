from tucam_control.row_groups import describe_row_groups


def test_custom_names_are_display_only_and_ids_remain_stable() -> None:
    groups = [(1, 10), (20, 30)]
    descriptors = describe_row_groups(
        groups,
        custom_names={
            "rows:1:10": "参考通道",
            "rows:20:30": "哈龙通道",
        },
    )

    assert [item.key for item in descriptors] == [
        "rows:1:10",
        "rows:20:30",
    ]
    assert [item.label for item in descriptors] == ["参考通道", "哈龙通道"]


def test_legacy_groups_receive_names_without_exposing_row_numbers() -> None:
    descriptors = describe_row_groups([(890, 930), (980, 1000)])

    assert [item.label for item in descriptors] == ["行组1", "行组2"]
