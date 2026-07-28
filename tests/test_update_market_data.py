from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from update_market_data import (
    cached_akshare_contract,
    cached_tushare_contract,
    closed_trade_dates,
    compare_source_overlap,
    contract_date_ranges,
    validate_mapping_product,
)


def test_closed_trade_dates_excludes_open_session_before_close() -> None:
    calendar = pd.DataFrame(
        {
            "cal_date": ["20260724", "20260727", "20260728"],
            "is_open": [1, 1, 1],
        }
    )
    now = datetime(2026, 7, 28, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    actual = closed_trade_dates(calendar, now=now)

    assert actual == ["2026-07-24", "2026-07-27"]


def test_closed_trade_dates_includes_today_after_market_close() -> None:
    calendar = pd.DataFrame({"cal_date": ["20260728"], "is_open": [1]})
    now = datetime(2026, 7, 28, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert closed_trade_dates(calendar, now=now) == ["2026-07-28"]


def test_contract_date_ranges_are_bounded_by_mapping() -> None:
    mapping = pd.DataFrame(
        {
            "trade_date": ["20260611", "20260612", "20260615"],
            "mapping_ts_code": ["T2606.CFX", "T2609.CFX", "T2609.CFX"],
        }
    )

    actual = contract_date_ranges(mapping)

    assert actual == [
        ("T2606.CFX", "2026-06-11", "2026-06-11"),
        ("T2609.CFX", "2026-06-12", "2026-06-15"),
    ]


def test_compare_source_overlap_reports_price_and_volume_differences() -> None:
    base = {
        "product": ["T"],
        "source_contract": ["T2609.CFX"],
        "datetime": [pd.Timestamp("2026-07-27 09:35:00")],
        "open": [108.1],
        "high": [108.2],
        "low": [108.0],
        "close": [108.15],
        "volume": [100],
        "open_interest": [200],
    }
    tushare = pd.DataFrame({**base, "source": ["tushare"]})
    akshare = pd.DataFrame(
        {
            **base,
            "close": [108.16],
            "volume": [101],
            "source": ["akshare"],
        }
    )

    actual = compare_source_overlap(tushare, akshare)

    assert actual["overlap_rows"] == 1
    assert actual["max_abs_close_diff"] == 0.01
    assert actual["volume_equal_rate"] == 0.0


def test_cached_tushare_contract_reuses_saved_normalized_bars(tmp_path) -> None:
    cache_path = tmp_path / "T2609.CFX.parquet"
    expected = pd.DataFrame(
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
        }
    )
    expected.to_parquet(cache_path, index=False)

    actual = cached_tushare_contract(
        pro=object(),
        product="T",
        ts_code="T2609.CFX",
        start_date="2026-06-12",
        end_date="2026-07-27",
        cache_path=cache_path,
    )

    pd.testing.assert_frame_equal(actual, expected)


def test_cached_akshare_contract_saves_fetch_result(tmp_path) -> None:
    class FakeAkshare:
        @staticmethod
        def futures_zh_minute_sina(*, symbol: str, period: str) -> pd.DataFrame:
            assert symbol == "T2609"
            assert period == "5"
            return pd.DataFrame(
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

    cache_path = tmp_path / "T2609.CFX.parquet"
    actual = cached_akshare_contract(
        akshare_module=FakeAkshare(),
        product="T",
        ts_code="T2609.CFX",
        start_date="2026-06-12",
        end_date="2026-07-27",
        cache_path=cache_path,
    )

    assert cache_path.exists()
    assert len(actual) == 1
    assert actual.loc[0, "source"] == "akshare"


def test_validate_mapping_product_rejects_t_contracts_for_tl() -> None:
    wrong = pd.DataFrame(
        {
            "trade_date": ["20260727"],
            "mapping_ts_code": ["T2609.CFX"],
        }
    )

    with pytest.raises(ValueError, match="expected TL"):
        validate_mapping_product(wrong, product="TL")
