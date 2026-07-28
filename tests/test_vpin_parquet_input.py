from __future__ import annotations

import pandas as pd
import pytest

from vpin_timing import read_tabular_file


def test_read_tabular_file_supports_parquet(tmp_path) -> None:
    path = tmp_path / "T_5min.parquet"
    expected = pd.DataFrame(
        {
            "datetime": [pd.Timestamp("2026-07-27 09:35:00")],
            "open": [108.1],
            "high": [108.2],
            "low": [108.0],
            "close": [108.15],
            "volume": [123],
            "open_interest": [456],
        }
    )
    expected.to_parquet(path, index=False)

    actual = read_tabular_file(path)

    pd.testing.assert_frame_equal(actual, expected)


def test_read_tabular_file_rejects_excel(tmp_path) -> None:
    with pytest.raises(ValueError, match="Unsupported file type"):
        read_tabular_file(tmp_path / "legacy.xlsx")
