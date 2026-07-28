"""Fully rebuild T/TL 5-minute research data with Tushare and AKShare."""

from __future__ import annotations

import argparse
import json
import os
import socket
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pandas as pd

from market_data import (
    build_continuous_series,
    merge_source_bars,
    normalize_akshare_minutes,
    normalize_tushare_minutes,
    validate_canonical_bars,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
PRODUCT_START_DATES = {"T": "20150320", "TL": "20230421"}
CONTINUOUS_CODES = {"T": "T.CFX", "TL": "TL0.CFX"}
def closed_trade_dates(
    calendar: pd.DataFrame,
    *,
    now: datetime | None = None,
) -> list[str]:
    """Return open CFFEX dates whose daytime session is known to be complete."""
    required = {"cal_date", "is_open"}
    missing = sorted(required.difference(calendar.columns))
    if missing:
        raise ValueError(f"trade calendar is missing columns: {missing}")
    current = now or datetime.now(tz=SHANGHAI)
    if current.tzinfo is None:
        current = current.replace(tzinfo=SHANGHAI)
    current = current.astimezone(SHANGHAI)
    today = current.date()

    result: list[str] = []
    for row in calendar.loc[calendar["is_open"].astype(int).eq(1)].itertuples():
        trade_date = pd.to_datetime(str(row.cal_date), format="%Y%m%d").date()
        if trade_date < today or (trade_date == today and current.hour >= 16):
            result.append(trade_date.isoformat())
    return sorted(set(result))


def contract_date_ranges(mapping: pd.DataFrame) -> list[tuple[str, str, str]]:
    """Collapse a daily mapping into one bounded request range per contract."""
    required = {"trade_date", "mapping_ts_code"}
    missing = sorted(required.difference(mapping.columns))
    if missing:
        raise ValueError(f"mapping is missing columns: {missing}")
    working = mapping[["trade_date", "mapping_ts_code"]].copy()
    working["trade_date"] = pd.to_datetime(
        working["trade_date"].astype(str), format="%Y%m%d", errors="raise"
    )
    ranges = (
        working.groupby("mapping_ts_code", sort=True)["trade_date"]
        .agg(["min", "max"])
        .reset_index()
    )
    return [
        (
            str(row.mapping_ts_code),
            row.min.date().isoformat(),
            row.max.date().isoformat(),
        )
        for row in ranges.itertuples(index=False)
    ]


def validate_mapping_product(mapping: pd.DataFrame, *, product: str) -> None:
    """Reject Tushare continuous-code aliases that map to another product."""
    if "mapping_ts_code" not in mapping.columns:
        raise ValueError("mapping is missing mapping_ts_code")
    prefixes = (
        mapping["mapping_ts_code"]
        .astype(str)
        .str.extract(r"^([A-Za-z]+)", expand=False)
        .str.upper()
    )
    unexpected = sorted(prefixes.dropna().loc[prefixes.ne(product)].unique())
    if unexpected:
        raise ValueError(
            f"Contract mapping for {product} has prefixes {unexpected}; expected {product}"
        )


def compare_source_overlap(
    tushare_bars: pd.DataFrame,
    akshare_bars: pd.DataFrame,
) -> dict[str, Any]:
    """Summarize like-for-like overlap without silently blending definitions."""
    keys = ["product", "source_contract", "datetime"]
    value_columns = ["open", "high", "low", "close", "volume", "open_interest"]
    if tushare_bars.empty or akshare_bars.empty:
        return {"overlap_rows": 0}
    overlap = tushare_bars[keys + value_columns].merge(
        akshare_bars[keys + value_columns],
        on=keys,
        how="inner",
        suffixes=("_tushare", "_akshare"),
    )
    if overlap.empty:
        return {"overlap_rows": 0}

    summary: dict[str, Any] = {"overlap_rows": int(len(overlap))}
    for column in ["open", "high", "low", "close"]:
        difference = (
            overlap[f"{column}_tushare"] - overlap[f"{column}_akshare"]
        ).abs()
        summary[f"max_abs_{column}_diff"] = round(float(difference.max()), 10)
        summary[f"{column}_equal_rate"] = round(float(difference.le(1e-12).mean()), 6)
    summary["volume_equal_rate"] = round(
        float(overlap["volume_tushare"].eq(overlap["volume_akshare"]).mean()), 6
    )
    summary["open_interest_equal_rate"] = round(
        float(
            overlap["open_interest_tushare"]
            .eq(overlap["open_interest_akshare"])
            .mean()
        ),
        6,
    )
    return summary


def _retry(
    operation: Callable[[], pd.DataFrame],
    *,
    label: str,
    attempts: int = 3,
) -> pd.DataFrame:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            result = operation()
            if not isinstance(result, pd.DataFrame):
                raise TypeError(f"{label} returned {type(result).__name__}, not DataFrame")
            return result
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < attempts:
                time.sleep(2**attempt)
    raise RuntimeError(f"{label} failed after {attempts} attempts: {last_error}") from last_error


def _fetch_tushare_contract(
    pro: Any,
    *,
    ts_code: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Fetch bounded chunks below the Tushare 8,000-row response ceiling."""
    cursor = pd.Timestamp(start_date)
    final = pd.Timestamp(end_date)
    chunks: list[pd.DataFrame] = []
    while cursor <= final:
        chunk_end = min(cursor + pd.Timedelta(days=119), final)
        label = f"Tushare ft_mins {ts_code} {cursor.date()}..{chunk_end.date()}"
        chunk = _retry(
            lambda start=cursor, end=chunk_end: pro.ft_mins(
                ts_code=ts_code,
                freq="5min",
                start_date=f"{start.date().isoformat()} 00:00:00",
                end_date=f"{end.date().isoformat()} 23:59:59",
            ),
            label=label,
        )
        if not chunk.empty:
            chunks.append(chunk)
        cursor = chunk_end + pd.Timedelta(days=1)
    if not chunks:
        return pd.DataFrame()
    return (
        pd.concat(chunks, ignore_index=True)
        .drop_duplicates(subset=["ts_code", "trade_time"], keep="last")
        .reset_index(drop=True)
    )


def _fetch_akshare_contract(
    akshare_module: Any,
    *,
    ts_code: str,
) -> pd.DataFrame:
    symbol = ts_code.split(".", maxsplit=1)[0]
    return _retry(
        lambda: akshare_module.futures_zh_minute_sina(symbol=symbol, period="5"),
        label=f"AKShare futures_zh_minute_sina {symbol}",
        attempts=2,
    )


def cached_tushare_contract(
    *,
    pro: Any,
    product: str,
    ts_code: str,
    start_date: str,
    end_date: str,
    cache_path: Path,
) -> pd.DataFrame:
    """Load one normalized contract cache or fetch and atomically create it."""
    if cache_path.exists():
        return pd.read_parquet(cache_path)
    raw = _fetch_tushare_contract(
        pro,
        ts_code=ts_code,
        start_date=start_date,
        end_date=end_date,
    )
    normalized = normalize_tushare_minutes(raw, product=product)
    _atomic_parquet(normalized, cache_path)
    return normalized


def cached_akshare_contract(
    *,
    akshare_module: Any,
    product: str,
    ts_code: str,
    start_date: str,
    end_date: str,
    cache_path: Path,
) -> pd.DataFrame:
    """Load one normalized AKShare cache or fetch the available active overlap."""
    if cache_path.exists():
        return pd.read_parquet(cache_path)
    raw = _fetch_akshare_contract(
        akshare_module,
        ts_code=ts_code,
    )
    normalized = normalize_akshare_minutes(
        raw,
        product=product,
        source_contract=ts_code,
    )
    if not normalized.empty:
        active = normalized["datetime"].between(
            pd.Timestamp(start_date),
            pd.Timestamp(end_date) + pd.Timedelta(days=1),
            inclusive="left",
        )
        normalized = normalized.loc[active].reset_index(drop=True)
    _atomic_parquet(normalized, cache_path)
    return normalized


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, path)


def _atomic_json(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _load_token(token_file: Path | None) -> str:
    environment_token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if environment_token:
        return environment_token
    if token_file is None:
        raise ValueError(
            "Set TUSHARE_TOKEN or pass --token-file with a local token file"
        )
    if not token_file.exists():
        raise FileNotFoundError(f"Tushare token file does not exist: {token_file}")
    token = token_file.read_text(encoding="utf-8-sig").strip()
    if not token:
        raise ValueError(f"Tushare token file is empty: {token_file}")
    return token


def update_product(
    *,
    product: str,
    pro: Any,
    akshare_module: Any,
    end_date: str,
    data_dir: Path,
) -> dict[str, Any]:
    start_date = PRODUCT_START_DATES[product]
    mapping = _retry(
        lambda: pro.fut_mapping(
            ts_code=CONTINUOUS_CODES[product],
            start_date=start_date,
            end_date=end_date,
        ),
        label=f"Tushare fut_mapping {product}",
    )
    if mapping.empty:
        raise RuntimeError(f"Tushare returned no contract mapping for {product}")
    mapping = mapping.loc[
        mapping["trade_date"].astype(str).between(start_date, end_date)
    ].copy()
    mapping = mapping.drop_duplicates(
        subset=["trade_date"], keep="last"
    ).sort_values("trade_date")
    validate_mapping_product(mapping, product=product)

    tushare_frames: list[pd.DataFrame] = []
    akshare_frames: list[pd.DataFrame] = []
    akshare_errors: dict[str, str] = {}
    ranges = contract_date_ranges(mapping)
    for index, (ts_code, contract_start, contract_end) in enumerate(ranges, start=1):
        print(
            f"[{product}] contract {index}/{len(ranges)} {ts_code} "
            f"{contract_start}..{contract_end}"
        )
        tushare_cache = (
            data_dir
            / "raw"
            / "tushare"
            / "contracts"
            / product
            / f"{ts_code}.parquet"
        )
        normalized_tushare = cached_tushare_contract(
            pro=pro,
            product=product,
            ts_code=ts_code,
            start_date=contract_start,
            end_date=contract_end,
            cache_path=tushare_cache,
        )
        if not normalized_tushare.empty:
            tushare_frames.append(normalized_tushare)
        try:
            akshare_cache = (
                data_dir
                / "raw"
                / "akshare"
                / "contracts"
                / product
                / f"{ts_code}.parquet"
            )
            normalized_akshare = cached_akshare_contract(
                akshare_module=akshare_module,
                product=product,
                ts_code=ts_code,
                start_date=contract_start,
                end_date=contract_end,
                cache_path=akshare_cache,
            )
            if not normalized_akshare.empty:
                akshare_frames.append(normalized_akshare)
        except Exception as exc:  # noqa: BLE001
            akshare_errors[ts_code] = str(exc)

    if not tushare_frames:
        raise RuntimeError(f"No Tushare minute bars were collected for {product}")
    tushare_bars = pd.concat(tushare_frames, ignore_index=True)
    akshare_bars = (
        pd.concat(akshare_frames, ignore_index=True)
        if akshare_frames
        else pd.DataFrame(columns=tushare_bars.columns)
    )
    merged = merge_source_bars(tushare_bars, akshare_bars)
    canonical = build_continuous_series(merged, mapping, product=product)
    mapping_dates = set(
        pd.to_datetime(mapping["trade_date"].astype(str), format="%Y%m%d")
        .dt.strftime("%Y-%m-%d")
        .tolist()
    )
    quality = validate_canonical_bars(
        canonical,
        open_trade_dates=mapping_dates,
        allow_missing_trade_dates=True,
    )
    overlap = compare_source_overlap(tushare_bars, akshare_bars)

    _atomic_parquet(
        tushare_bars,
        data_dir / "raw" / "tushare" / f"{product}_5min.parquet",
    )
    _atomic_parquet(
        akshare_bars,
        data_dir / "raw" / "akshare" / f"{product}_5min.parquet",
    )
    _atomic_parquet(
        canonical,
        data_dir / "canonical" / f"{product}_5min.parquet",
    )
    return {
        "product": product,
        "start_date": start_date,
        "end_date": end_date,
        "mapping_rows": int(len(mapping)),
        "quality": quality,
        "source_overlap": overlap,
        "akshare_errors": akshare_errors,
        "mapping": mapping,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fully rebuild T/TL 5-minute data with Tushare and AKShare."
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        default=None,
        help="Optional local Tushare token file; TUSHARE_TOKEN takes precedence.",
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--end-date",
        help="Optional YYYYMMDD ceiling; defaults to the latest completed CFFEX day.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    token = _load_token(args.token_file)
    socket.setdefaulttimeout(30)

    import akshare as ak
    import tushare as ts

    pro = ts.pro_api(token)
    now = datetime.now(tz=SHANGHAI)
    requested_end = args.end_date or now.strftime("%Y%m%d")
    calendar = _retry(
        lambda: pro.fut_trade_cal(
            exchange="CFFEX",
            start_date=min(PRODUCT_START_DATES.values()),
            end_date=requested_end,
        ),
        label="Tushare fut_trade_cal CFFEX",
    )
    complete_dates = closed_trade_dates(calendar, now=now)
    if args.end_date:
        ceiling = pd.to_datetime(args.end_date, format="%Y%m%d").date()
        complete_dates = [
            trade_date
            for trade_date in complete_dates
            if pd.Timestamp(trade_date).date() <= ceiling
        ]
    if not complete_dates:
        raise RuntimeError("No completed CFFEX trade date is available")
    end_date = complete_dates[-1].replace("-", "")
    print(f"Latest completed CFFEX trade date: {end_date}")

    results = []
    mappings = []
    for product in ["T", "TL"]:
        result = update_product(
            product=product,
            pro=pro,
            akshare_module=ak,
            end_date=end_date,
            data_dir=args.data_dir,
        )
        mappings.append(result.pop("mapping").assign(product=product))
        results.append(result)

    combined_mapping = pd.concat(mappings, ignore_index=True)
    _atomic_parquet(
        combined_mapping,
        args.data_dir / "metadata" / "contract_mapping.parquet",
    )
    manifest = {
        "generated_at": datetime.now(tz=SHANGHAI).isoformat(),
        "latest_completed_trade_date": end_date,
        "frequency": "5min",
        "canonical_source_policy": "tushare_primary_akshare_exact_gap_fill",
        "products": results,
    }
    _atomic_json(manifest, args.data_dir / "metadata" / "latest_update.json")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
