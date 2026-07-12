from __future__ import annotations

import numpy as np

from tucam_control.data_processor import DataProcessor


def test_row_groups_default_to_sum() -> None:
    image = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint16)
    processor = DataProcessor()
    processor.row_groups = [(1, 2)]

    result = processor.process(image)

    np.testing.assert_array_equal(result, [[5.0, 7.0, 9.0]])


def test_row_groups_can_use_mean() -> None:
    image = np.array([[1, 2, 3], [3, 4, 5]], dtype=np.uint16)
    processor = DataProcessor()
    processor.row_groups = [(1, 2)]
    processor.row_aggregation = DataProcessor.ROW_AGGREGATION_MEAN

    result = processor.process(image)

    np.testing.assert_array_equal(result, [[2.0, 3.0, 4.0]])
