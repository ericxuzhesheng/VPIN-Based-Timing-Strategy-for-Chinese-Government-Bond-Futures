"""Canonical market-data transformations for T/TL futures research."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

import pandas as pd


CANONICAL_COLUMNS = [
    "product",
    "source_contract",
    "datetime",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "open_interest",
    "source",
]


class DataQualityError(ValueError):
    """Raised when canonical bars violate a required data-quality invariant."""


def _canonicalize(
    raw: pd.DataFrame,
    *,
    product: str,
    source: str,
    datetime_column: str,
    volume_column: str,
    open_interest_column: str,
    source_contract: str | None = None,
) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    required = {
        datetime_column,
        "open",
        "high",
        "low",
        "close",
        volume_column,
        open_interest_column,
    }
    missing = sorted(required.difference(raw.columns))
    if missing:
        raise DataQualityError(f"{source} data is missing columns: {missing}")

    result = pd.DataFrame(index=raw.index)
    result["product"] = product
    if source_contract is None:
        if "ts_code" not in raw.columns:
            raise DataQualityError("tushare data is missing ts_code")
        result["source_contract"] = raw["ts_code"].astype(str)
    else:
        result["source_contract"] = source_contract
    result["datetime"] = pd.to_datetime(raw[datetime_column], errors="coerce")
    for column in ["open", "high", "low", "close"]:
        result[column] = pd.to_numeric(raw[column], errors="coerce")
    result["volume"] = pd.to_numeric(raw[volume_column], errors="coerce")
    result["open_interest"] = pd.to_numeric(raw[open_interest_column], errors="coerce")
    result["source"] = source
    result = result.dropna(
        subset=["source_contract", "datetime", "open", "high", "low", "close", "volume"]
    )
    return (
        result[CANONICAL_COLUMNS]
        .drop_duplicates(subset=["source_contract", "datetime"], keep="last")
        .sort_values(["source_contract", "datetime"])
        .reset_index(drop=True)
    )


def normalize_tushare_minutes(raw: pd.DataFrame, *, product: str) -> pd.DataFrame:
    """Convert ``ft_mins`` output to the canonical minute-bar schema."""
    return _canonicalize(
        raw,
        product=product,
        source="tushare",
        datetime_column="trade_time",
        volume_column="vol",
        open_interest_column="oi",
    )


def normalize_akshare_minutes(
    raw: pd.DataFrame,
    *,
    product: str,
    source_contract: str,
) -> pd.DataFrame:
    """Convert ``futures_zh_minute_sina`` output to the canonical schema."""
    return _canonicalize(
        raw,
        product=product,
        source="akshare",
        datetime_column="datetime",
        volume_column="volume",
        open_interest_column="hold",
        source_contract=source_contract,
    )


def merge_source_bars(
    tushare_bars: pd.DataFrame,
    akshare_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Prefer Tushare while allowing AKShare to fill exact missing contract bars."""
    frames = []
    if not tushare_bars.empty:
        primary = tushare_bars.copy()
        primary["_priority"] = 0
        frames.append(primary)
    if not akshare_bars.empty:
        secondary = akshare_bars.copy()
        secondary["_priority"] = 1
        frames.append(secondary)
    if not frames:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    combined = pd.concat(frames, ignore_index=True)
    return (
        combined.sort_values(["source_contract", "datetime", "_priority"])
        .drop_duplicates(subset=["source_contract", "datetime"], keep="first")
        .drop(columns="_priority")
        .sort_values("datetime")
        .reset_index(drop=True)
    )


def build_continuous_series(
    bars: pd.DataFrame,
    mapping: pd.DataFrame,
    *,
    product: str,
) -> pd.DataFrame:
    """Select the mapped concrete contract on each trade date and mark rolls."""
    required_mapping = {"trade_date", "mapping_ts_code"}
    missing = sorted(required_mapping.difference(mapping.columns))
    if missing:
        raise DataQualityError(f"mapping data is missing columns: {missing}")
    if bars.empty or mapping.empty:
        raise DataQualityError(f"No bars or mapping rows available for {product}")

    daily_mapping = mapping[["trade_date", "mapping_ts_code"]].copy()
    daily_mapping["trade_date"] = pd.to_datetime(
        daily_mapping["trade_date"].astype(str), format="%Y%m%d", errors="coerce"
    ).dt.normalize()
    daily_mapping = (
        daily_mapping.dropna()
        .drop_duplicates(subset="trade_date", keep="last")
        .sort_values("trade_date")
    )
    daily_mapping["roll_flag"] = daily_mapping["mapping_ts_code"].ne(
        daily_mapping["mapping_ts_code"].shift()
    )
    if not daily_mapping.empty:
        daily_mapping.iloc[0, daily_mapping.columns.get_loc("roll_flag")] = False

    candidates = bars.loc[bars["product"].eq(product)].copy()
    candidates["trade_date"] = candidates["datetime"].dt.normalize()
    selected = candidates.merge(daily_mapping, on="trade_date", how="inner")
    selected = selected.loc[
        selected["source_contract"].eq(selected["mapping_ts_code"])
    ].copy()
    selected = selected.drop(columns=["trade_date", "mapping_ts_code"])
    selected = selected.sort_values("datetime").reset_index(drop=True)
    if selected.empty:
        raise DataQualityError(f"No mapped bars remain for {product}")
    return selected


def validate_canonical_bars(
    bars: pd.DataFrame,
    *,
    open_trade_dates: Collection[str],
) -> dict[str, Any]:
    """Validate canonical bars and return a JSON-serializable summary."""
    required = set(CANONICAL_COLUMNS) | {"roll_flag"}
    missing = sorted(required.difference(bars.columns))
    if missing:
        raise DataQualityError(f"canonical data is missing columns: {missing}")
    if bars.empty:
        raise DataQualityError("canonical data is empty")
    if bars["datetime"].duplicated().any():
        raise DataQualityError("duplicate canonical timestamps detected")
    if not bars["datetime"].is_monotonic_increasing:
        raise DataQualityError("canonical timestamps are not increasing")

    observed_dates = set(bars["datetime"].dt.strftime("%Y-%m-%d"))
    unexpected_dates = sorted(observed_dates.difference(set(open_trade_dates)))
    if unexpected_dates:
        raise DataQualityError(f"non-trading dates detected: {unexpected_dates[:5]}")

    bad_ohlc = (
        bars["high"].lt(bars[["open", "close", "low"]].max(axis=1))
        | bars["low"].gt(bars[["open", "close", "high"]].min(axis=1))
    )
    if bad_ohlc.any():
        raise DataQualityError("invalid OHLC relationship detected")
    if bars["volume"].lt(0).any() or bars["open_interest"].dropna().lt(0).any():
        raise DataQualityError("negative volume or open interest detected")

    source_rows = {
        str(source): int(count)
        for source, count in bars["source"].value_counts().sort_index().items()
    }
    return {
        "rows": int(len(bars)),
        "first_datetime": bars["datetime"].min().isoformat(),
        "last_datetime": bars["datetime"].max().isoformat(),
        "trade_dates": int(bars["datetime"].dt.normalize().nunique()),
        "contracts": int(bars["source_contract"].nunique()),
        "rolls": int(bars["roll_flag"].sum()),
        "source_rows": source_rows,
    }
