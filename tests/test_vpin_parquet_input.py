from __future__ import annotations

import pandas as pd
import pytest

from vpin_timing import (
    aggregate_vpin_to_daily,
    calculate_vpin,
    read_tabular_file,
    standardize_columns,
)


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


def test_standardize_columns_preserves_contract_lineage() -> None:
    raw = pd.DataFrame(
        {
            "datetime": [pd.Timestamp("2026-07-27 09:35:00")],
            "open": [108.1],
            "high": [108.2],
            "low": [108.0],
            "close": [108.15],
            "volume": [123],
            "open_interest": [456],
            "source_contract": ["T2609.CFX"],
            "roll_flag": [True],
        }
    )

    actual = standardize_columns(raw)

    assert actual.loc[0, "source_contract"] == "T2609.CFX"
    assert bool(actual.loc[0, "roll_flag"]) is True


def test_calculate_vpin_resets_rolling_state_at_contract_roll() -> None:
    first_times = pd.date_range("2026-06-11 14:30:00", periods=10, freq="5min")
    second_times = pd.date_range("2026-06-12 09:35:00", periods=10, freq="5min")
    intraday = pd.DataFrame(
        {
            "datetime": first_times.append(second_times),
            "open": [103.0] * 10 + [104.0] * 10,
            "high": [103.1] * 10 + [104.1] * 10,
            "low": [102.9] * 10 + [103.9] * 10,
            "close": [103.0 + index * 0.01 for index in range(10)]
            + [104.0 + index * 0.01 for index in range(10)],
            "volume": [100] * 20,
            "open_interest": list(range(1000, 1010)) + list(range(1100, 1110)),
            "source_contract": ["T2606.CFX"] * 10 + ["T2609.CFX"] * 10,
            "roll_flag": [False] * 10 + [True] * 10,
        }
    )

    actual = calculate_vpin(
        intraday,
        classification_method="tick",
        vpin_window=5,
        slope_window=5,
        zscore_window=5,
        percentile_window=10,
    )

    assert pd.isna(actual.loc[10, "rolling_vpin"])
    assert pd.notna(actual.loc[14, "rolling_vpin"])


def test_daily_return_excludes_cross_contract_roll_jump() -> None:
    intraday = pd.DataFrame(
        {
            "datetime": pd.to_datetime(
                ["2026-06-11 15:15:00", "2026-06-12 15:15:00"]
            ),
            "close": [103.0, 104.0],
            "rolling_vpin": [0.4, 0.5],
            "roll_flag": [False, True],
        }
    )

    actual = aggregate_vpin_to_daily(
        intraday,
        daily_slope_window=2,
        daily_stats_window=10,
    )

    assert pd.isna(actual.loc[1, "daily_return"])
