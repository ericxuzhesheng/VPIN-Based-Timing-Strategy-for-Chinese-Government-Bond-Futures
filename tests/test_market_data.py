from __future__ import annotations

import pandas as pd
import pytest

from market_data import (
    DataQualityError,
    build_continuous_series,
    merge_source_bars,
    normalize_akshare_minutes,
    normalize_tushare_minutes,
    validate_canonical_bars,
)


def test_normalize_tushare_minutes_produces_canonical_schema() -> None:
    raw = pd.DataFrame(
        {
            "ts_code": ["T2609.CFX"],
            "trade_time": ["2026-07-27 09:35:00"],
            "open": [108.1],
            "high": [108.2],
            "low": [108.0],
            "close": [108.15],
            "vol": [123],
            "oi": [456],
        }
    )

    actual = normalize_tushare_minutes(raw, product="T")

    assert actual.to_dict("records") == [
        {
            "product": "T",
            "source_contract": "T2609.CFX",
            "datetime": pd.Timestamp("2026-07-27 09:35:00"),
            "open": 108.1,
            "high": 108.2,
            "low": 108.0,
            "close": 108.15,
            "volume": 123,
            "open_interest": 456,
            "source": "tushare",
        }
    ]


def test_normalize_akshare_minutes_uses_requested_contract() -> None:
    raw = pd.DataFrame(
        {
            "datetime": ["2026-07-27 09:35:00"],
            "open": [108.1],
            "high": [108.2],
            "low": [108.0],
            "close": [108.15],
            "volume": [123],
            "hold": [456],
        }
    )

    actual = normalize_akshare_minutes(raw, product="T", source_contract="T2609.CFX")

    assert actual.loc[0, "source_contract"] == "T2609.CFX"
    assert actual.loc[0, "open_interest"] == 456
    assert actual.loc[0, "source"] == "akshare"


def test_merge_source_bars_prefers_tushare_and_fills_only_missing_bars() -> None:
    tushare = normalize_tushare_minutes(
        pd.DataFrame(
            {
                "ts_code": ["T2609.CFX"],
                "trade_time": ["2026-07-27 09:35:00"],
                "open": [108.1],
                "high": [108.2],
                "low": [108.0],
                "close": [108.15],
                "vol": [123],
                "oi": [456],
            }
        ),
        product="T",
    )
    akshare = normalize_akshare_minutes(
        pd.DataFrame(
            {
                "datetime": ["2026-07-27 09:35:00", "2026-07-27 09:40:00"],
                "open": [999.0, 108.15],
                "high": [999.0, 108.25],
                "low": [999.0, 108.1],
                "close": [999.0, 108.2],
                "volume": [999, 100],
                "hold": [999, 460],
            }
        ),
        product="T",
        source_contract="T2609.CFX",
    )

    actual = merge_source_bars(tushare, akshare)

    assert actual["close"].tolist() == [108.15, 108.2]
    assert actual["source"].tolist() == ["tushare", "akshare"]


def test_build_continuous_series_uses_daily_mapping_and_marks_roll() -> None:
    bars = normalize_tushare_minutes(
        pd.DataFrame(
            {
                "ts_code": ["T2606.CFX", "T2609.CFX", "T2606.CFX"],
                "trade_time": [
                    "2026-06-11 15:15:00",
                    "2026-06-12 09:35:00",
                    "2026-06-12 09:35:00",
                ],
                "open": [103.0, 104.0, 999.0],
                "high": [103.1, 104.1, 999.0],
                "low": [102.9, 103.9, 999.0],
                "close": [103.0, 104.0, 999.0],
                "vol": [100, 110, 999],
                "oi": [1000, 1100, 999],
            }
        ),
        product="T",
    )
    mapping = pd.DataFrame(
        {
            "trade_date": ["20260611", "20260612"],
            "mapping_ts_code": ["T2606.CFX", "T2609.CFX"],
        }
    )

    actual = build_continuous_series(bars, mapping, product="T")

    assert actual["close"].tolist() == [103.0, 104.0]
    assert actual["roll_flag"].tolist() == [False, True]


def test_validate_canonical_bars_rejects_weekend_and_duplicate_timestamp() -> None:
    invalid = pd.DataFrame(
        {
            "product": ["TL", "TL"],
            "source_contract": ["TL2606.CFX", "TL2606.CFX"],
            "datetime": [
                pd.Timestamp("2026-04-25 09:35:00"),
                pd.Timestamp("2026-04-25 09:35:00"),
            ],
            "open": [110.0, 110.0],
            "high": [110.1, 110.1],
            "low": [109.9, 109.9],
            "close": [110.0, 110.0],
            "volume": [1, 1],
            "open_interest": [1, 1],
            "source": ["tushare", "tushare"],
            "roll_flag": [False, False],
        }
    )

    with pytest.raises(DataQualityError, match="duplicate|non-trading"):
        validate_canonical_bars(invalid, open_trade_dates={"2026-04-24"})


def test_validate_canonical_bars_returns_bounded_quality_summary() -> None:
    valid = pd.DataFrame(
        {
            "product": ["T", "T"],
            "source_contract": ["T2609.CFX", "T2609.CFX"],
            "datetime": [
                pd.Timestamp("2026-07-27 09:35:00"),
                pd.Timestamp("2026-07-27 09:40:00"),
            ],
            "open": [108.1, 108.15],
            "high": [108.2, 108.25],
            "low": [108.0, 108.1],
            "close": [108.15, 108.2],
            "volume": [123, 100],
            "open_interest": [456, 460],
            "source": ["tushare", "akshare"],
            "roll_flag": [False, False],
        }
    )

    summary = validate_canonical_bars(valid, open_trade_dates={"2026-07-27"})

    assert summary["rows"] == 2
    assert summary["first_datetime"] == "2026-07-27T09:35:00"
    assert summary["last_datetime"] == "2026-07-27T09:40:00"
    assert summary["source_rows"] == {"akshare": 1, "tushare": 1}


def test_validate_canonical_bars_rejects_missing_mapped_trade_date() -> None:
    valid = pd.DataFrame(
        {
            "product": ["T"],
            "source_contract": ["T2609.CFX"],
            "datetime": [pd.Timestamp("2026-07-27 09:35:00")],
            "open": [108.1],
            "high": [108.2],
            "low": [108.0],
            "close": [108.15],
            "volume": [123],
            "open_interest": [456],
            "source": ["tushare"],
            "roll_flag": [False],
        }
    )

    with pytest.raises(DataQualityError, match="missing trade dates"):
        validate_canonical_bars(
            valid,
            open_trade_dates={"2026-07-24", "2026-07-27"},
        )


def test_validate_canonical_bars_can_report_known_source_gaps() -> None:
    bars = pd.DataFrame(
        {
            "product": ["T"],
            "source_contract": ["T2609.CFX"],
            "datetime": [pd.Timestamp("2026-07-27 09:35:00")],
            "open": [108.1],
            "high": [108.2],
            "low": [108.0],
            "close": [108.15],
            "volume": [123],
            "open_interest": [456],
            "source": ["tushare"],
            "roll_flag": [False],
        }
    )

    summary = validate_canonical_bars(
        bars,
        open_trade_dates={"2026-07-24", "2026-07-27"},
        allow_missing_trade_dates=True,
    )

    assert summary["missing_trade_dates"] == ["2026-07-24"]
