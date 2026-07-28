from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from update_market_data import (
    closed_trade_dates,
    compare_source_overlap,
    contract_date_ranges,
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
