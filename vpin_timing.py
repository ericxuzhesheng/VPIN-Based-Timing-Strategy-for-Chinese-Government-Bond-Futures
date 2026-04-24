from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DEFAULT_INPUTS = {
    "T": Path("10年国债期货_5min_3年.xlsx"),
    "TL": Path("30年国债期货_5min_2年.xlsx"),
}
CONTRACT_CHOICES = ["T", "TL", "ALL"]

CONTRACT_LABELS = {
    "T": "10Y Treasury Futures",
    "TL": "30Y Treasury Futures",
}

COLUMN_ALIASES = {
    "datetime": "datetime",
    "date": "datetime",
    "time": "datetime",
    "timestamp": "datetime",
    "trade_time": "datetime",
    "trade_date": "datetime",
    "时间": "datetime",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "持仓量": "open_interest",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "vol": "volume",
    "oi": "open_interest",
    "open_interest": "open_interest",
    "openinterest": "open_interest",
}

REQUIRED_COLUMNS = ["datetime", "open", "high", "low", "close", "volume"]
OUTPUT_INTRADAY_COLUMNS = [
    "contract",
    "datetime",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "open_interest",
    "buy_volume",
    "sell_volume",
    "volume_imbalance",
    "rolling_vpin",
    "vpin_slope",
    "vpin_zscore",
    "vpin_percentile",
]
OUTPUT_DAILY_COLUMNS = [
    "contract",
    "date",
    "daily_close",
    "daily_return",
    "daily_mean_vpin",
    "daily_max_vpin",
    "daily_vpin_slope",
    "daily_vpin_zscore",
    "daily_vpin_percentile",
    "future_return",
    "signal_raw",
    "position",
    "vpin_high_flag",
    "slope_positive_flag",
]
OUTPUT_NAV_COLUMNS = [
    "contract",
    "date",
    "position",
    "turnover",
    "strategy_return",
    "benchmark_return",
    "strategy_nav",
    "benchmark_nav",
    "strategy_drawdown",
    "benchmark_drawdown",
]


def load_intraday_data(input_path: Path, start_date: str | None = None) -> pd.DataFrame:
    """Load minute data from csv or Excel and return a standardized DataFrame."""
    if not input_path.exists():
        raise FileNotFoundError(f"Input file does not exist: {input_path}")

    raw_df = read_tabular_file(input_path)
    standardized = standardize_columns(raw_df)

    if start_date is not None:
        start_ts = pd.to_datetime(start_date, errors="raise")
        standardized = standardized.loc[standardized["datetime"] >= start_ts].copy()

    if standardized.empty:
        raise ValueError("No rows remain after loading and date filtering.")

    time_delta = standardized["datetime"].diff().dropna()
    if not time_delta.empty:
        median_delta = time_delta.median()
        print(f"Detected median bar interval: {median_delta}")

    return standardized.reset_index(drop=True)


def read_tabular_file(input_path: Path) -> pd.DataFrame:
    """Read csv or Excel input into a raw DataFrame."""
    suffix = input_path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(input_path)

    if suffix == ".csv":
        encodings = ["utf-8-sig", "utf-8", "gbk", "gb2312"]
        last_error: Exception | None = None
        for encoding in encodings:
            try:
                return pd.read_csv(input_path, encoding=encoding)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        raise ValueError(f"Failed to read csv file with supported encodings: {last_error}")

    raise ValueError(f"Unsupported file type: {suffix}. Use csv, xls, or xlsx.")


def standardize_columns(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Rename raw columns into the standard research schema."""
    if raw_df.empty:
        raise ValueError("Input data is empty.")

    rename_map: dict[str, str] = {}
    for column in raw_df.columns:
        key = normalize_column_name(column)
        if key in COLUMN_ALIASES:
            rename_map[column] = COLUMN_ALIASES[key]

    df = raw_df.rename(columns=rename_map).copy()
    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(
            f"Missing required columns after standardization: {missing}. "
            f"Expected columns include {REQUIRED_COLUMNS} and optional open_interest."
        )

    if "open_interest" not in df.columns:
        df["open_interest"] = np.nan

    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    if df["datetime"].isna().all():
        raise ValueError("Failed to parse any datetime values from the input file.")

    numeric_columns = ["open", "high", "low", "close", "volume", "open_interest"]
    for column in numeric_columns:
        df[column] = pd.to_numeric(
            df[column].astype(str).str.replace(",", "", regex=False),
            errors="coerce",
        )

    df = (
        df[["datetime", "open", "high", "low", "close", "volume", "open_interest"]]
        .dropna(subset=REQUIRED_COLUMNS)
        .drop_duplicates(subset="datetime", keep="last")
        .sort_values("datetime")
        .reset_index(drop=True)
    )

    if df.empty:
        raise ValueError("No valid rows remain after standardization and cleaning.")

    return df


def normalize_column_name(name: Any) -> str:
    """Normalize a raw column name for alias matching."""
    text = str(name).strip().lower().replace("-", "_").replace(" ", "_")
    return text


def calculate_vpin(
    intraday_df: pd.DataFrame,
    classification_method: str = "bvc",
    classification_window: int = 50,
    vpin_window: int = 50,
    slope_window: int = 10,
    zscore_window: int = 100,
    percentile_window: int = 100,
) -> pd.DataFrame:
    """Compute intraday VPIN and supporting order-flow toxicity features."""
    if intraday_df.empty:
        raise ValueError("Intraday input is empty.")
    if vpin_window < 2:
        raise ValueError("vpin_window must be at least 2.")

    df = intraday_df.copy()
    price_change = df["close"].diff()
    price_change.iloc[0] = df["close"].iloc[0] - df["open"].iloc[0]
    fallback_move = (df["close"] - df["open"]).replace(0, np.nan)
    price_change = price_change.where(price_change.ne(0), fallback_move).fillna(0.0)

    if classification_method == "bvc":
        sigma = price_change.rolling(
            classification_window,
            min_periods=max(5, classification_window // 3),
        ).std()
        sigma = sigma.fillna(price_change.expanding(min_periods=2).std())
        z_value = (price_change / sigma.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
        buy_ratio = normal_cdf(z_value.fillna(0.0)).clip(0.0, 1.0)
    elif classification_method == "tick":
        buy_ratio = pd.Series(0.5, index=df.index, dtype=float)
        buy_ratio = buy_ratio.mask(price_change > 0, 1.0)
        buy_ratio = buy_ratio.mask(price_change < 0, 0.0)
    else:
        raise ValueError("classification_method must be 'bvc' or 'tick'.")

    df["buy_volume"] = df["volume"] * buy_ratio
    df["sell_volume"] = df["volume"] - df["buy_volume"]
    df["volume_imbalance"] = (df["buy_volume"] - df["sell_volume"]).abs()

    imbalance_sum = df["volume_imbalance"].rolling(
        vpin_window,
        min_periods=vpin_window,
    ).sum()
    total_volume_sum = df["volume"].rolling(vpin_window, min_periods=vpin_window).sum()
    df["rolling_vpin"] = imbalance_sum / total_volume_sum.replace(0, np.nan)
    df["vpin_slope"] = rolling_linear_slope(df["rolling_vpin"], slope_window)
    df["vpin_zscore"] = rolling_zscore(df["rolling_vpin"], zscore_window)
    df["vpin_percentile"] = rolling_percentile_rank(df["rolling_vpin"], percentile_window)
    return df


def normal_cdf(values: pd.Series) -> pd.Series:
    """Return the standard normal CDF with a scipy-free fallback."""
    try:
        from scipy.stats import norm

        result = norm.cdf(values.to_numpy(dtype=float))
        return pd.Series(result, index=values.index, dtype=float)
    except Exception:  # noqa: BLE001
        scaled = values.to_numpy(dtype=float) / math.sqrt(2.0)
        result = np.array([0.5 * (1.0 + math.erf(value)) for value in scaled], dtype=float)
        return pd.Series(result, index=values.index, dtype=float)


def rolling_linear_slope(series: pd.Series, window: int) -> pd.Series:
    """Estimate a rolling linear slope using least squares."""
    if window < 2:
        raise ValueError("window must be at least 2 for slope estimation.")

    x = np.arange(window, dtype=float)
    x_centered = x - x.mean()
    denominator = np.sum(x_centered**2)

    def _slope(values: np.ndarray) -> float:
        if np.isnan(values).any():
            return float("nan")
        y_centered = values - values.mean()
        return float(np.dot(x_centered, y_centered) / denominator)

    return series.rolling(window, min_periods=window).apply(_slope, raw=True)


def rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    """Compute a rolling z-score."""
    min_periods = max(5, window // 2)
    rolling_mean = series.rolling(window, min_periods=min_periods).mean()
    rolling_std = series.rolling(window, min_periods=min_periods).std()
    return (series - rolling_mean) / rolling_std.replace(0, np.nan)


def rolling_percentile_rank(series: pd.Series, window: int) -> pd.Series:
    """Compute the percentile rank of the latest point inside a rolling window."""
    min_periods = max(10, window // 2)

    def _percentile(values: np.ndarray) -> float:
        valid = values[~np.isnan(values)]
        if len(valid) == 0:
            return float("nan")
        latest = valid[-1]
        return float(np.mean(valid <= latest))

    return series.rolling(window, min_periods=min_periods).apply(_percentile, raw=True)


def aggregate_vpin_to_daily(
    intraday_vpin: pd.DataFrame,
    daily_slope_window: int = 5,
    daily_stats_window: int = 60,
) -> pd.DataFrame:
    """Aggregate minute-level VPIN features into a daily research table."""
    df = intraday_vpin.copy()
    df["date"] = df["datetime"].dt.normalize()

    daily = (
        df.groupby("date", as_index=False)
        .agg(
            daily_close=("close", "last"),
            daily_mean_vpin=("rolling_vpin", "mean"),
            daily_max_vpin=("rolling_vpin", "max"),
        )
        .sort_values("date")
        .reset_index(drop=True)
    )

    if daily.empty:
        raise ValueError("Daily aggregation produced no rows.")

    daily["daily_return"] = daily["daily_close"].pct_change()
    daily["daily_vpin_slope"] = rolling_linear_slope(daily["daily_mean_vpin"], daily_slope_window)
    daily["daily_vpin_zscore"] = rolling_zscore(daily["daily_mean_vpin"], daily_stats_window)
    daily["daily_vpin_percentile"] = rolling_percentile_rank(
        daily["daily_mean_vpin"],
        daily_stats_window,
    )
    daily["future_return"] = daily["daily_return"].shift(-1)
    return daily


def generate_vpin_signal(
    daily_vpin: pd.DataFrame,
    high_percentile_threshold: float = 0.8,
    slope_threshold: float = 0.0,
    long_position: float = 1.0,
    defensive_position: float = 0.0,
) -> pd.DataFrame:
    """Generate a lagged daily VPIN timing signal with a long-or-defensive exposure."""
    df = daily_vpin.copy().sort_values("date").reset_index(drop=True)
    df["vpin_high_flag"] = df["daily_vpin_percentile"] >= high_percentile_threshold
    df["slope_positive_flag"] = df["daily_vpin_slope"] > slope_threshold
    toxic_flow_flag = df["vpin_high_flag"] & df["slope_positive_flag"]
    
    # Toxic flow leads to defensive position, otherwise stay long
    df["signal_raw"] = np.where(toxic_flow_flag, defensive_position, long_position)
    df["position"] = df["signal_raw"].shift(1).fillna(long_position)
    return df


def run_backtest(
    daily_signal_df: pd.DataFrame,
    transaction_cost: float = 0.0,
) -> pd.DataFrame:
    """Run a daily close-to-close backtest against a long-only benchmark."""
    df = daily_signal_df.copy().sort_values("date").reset_index(drop=True)
    df["daily_return"] = df["daily_return"].fillna(0.0)
    df["turnover"] = df["position"].diff().abs().fillna(0.0)
    df["benchmark_return"] = df["daily_return"]
    df["strategy_return"] = df["position"] * df["daily_return"] - transaction_cost * df["turnover"]
    df["strategy_nav"] = (1.0 + df["strategy_return"]).cumprod()
    df["benchmark_nav"] = (1.0 + df["benchmark_return"]).cumprod()
    df["strategy_drawdown"] = compute_drawdown(df["strategy_nav"])
    df["benchmark_drawdown"] = compute_drawdown(df["benchmark_nav"])
    return df


def compute_drawdown(nav: pd.Series) -> pd.Series:
    """Compute running drawdown from a net asset value series."""
    running_max = nav.cummax()
    return nav / running_max - 1.0


def calculate_performance_metrics(
    backtest_df: pd.DataFrame,
    contract: str,
    annualization: int = 252,
) -> pd.DataFrame:
    """Calculate performance metrics for the VPIN strategy and the benchmark."""
    strategy_row = performance_row(
        name="vpin_strategy",
        contract=contract,
        returns=backtest_df["strategy_return"],
        nav=backtest_df["strategy_nav"],
        turnover=backtest_df["turnover"],
        annualization=annualization,
    )
    benchmark_row = performance_row(
        name="long_only_benchmark",
        contract=contract,
        returns=backtest_df["benchmark_return"],
        nav=backtest_df["benchmark_nav"],
        turnover=pd.Series(0.0, index=backtest_df.index),
        annualization=annualization,
    )
    metrics = pd.DataFrame([strategy_row, benchmark_row])
    numeric_columns = metrics.select_dtypes(include="number").columns
    metrics[numeric_columns] = metrics[numeric_columns].round(6)
    return metrics


def performance_row(
    name: str,
    contract: str,
    returns: pd.Series,
    nav: pd.Series,
    turnover: pd.Series,
    annualization: int,
) -> dict[str, Any]:
    """Build a single metrics row for a return stream."""
    clean_returns = returns.fillna(0.0)
    clean_nav = nav.ffill().fillna(1.0)
    periods = len(clean_returns)
    if periods == 0:
        raise ValueError("Cannot calculate metrics on an empty backtest.")

    cumulative_return = float(clean_nav.iloc[-1] - 1.0)
    annualized_return = float(clean_nav.iloc[-1] ** (annualization / periods) - 1.0)
    annualized_volatility = float(clean_returns.std(ddof=0) * math.sqrt(annualization))
    sharpe_ratio = (
        float(annualized_return / annualized_volatility)
        if annualized_volatility > 0
        else float("nan")
    )
    drawdown = compute_drawdown(clean_nav)
    max_drawdown = float(abs(drawdown.min()))
    calmar_ratio = float(annualized_return / max_drawdown) if max_drawdown > 0 else float("nan")
    win_rate = float((clean_returns > 0).mean())
    turnover_metric = float(turnover.fillna(0.0).mean())

    return {
        "contract": contract,
        "strategy": name,
        "cumulative_return": cumulative_return,
        "annualized_return": annualized_return,
        "annualized_volatility": annualized_volatility,
        "sharpe_ratio": sharpe_ratio,
        "max_drawdown": max_drawdown,
        "calmar_ratio": calmar_ratio,
        "win_rate": win_rate,
        "turnover": turnover_metric,
    }


def plot_price_and_vpin(daily_df: pd.DataFrame, output_path: Path, contract: str) -> None:
    """Plot daily close alongside VPIN."""
    fig, ax_price = plt.subplots(figsize=(12, 6))
    ax_vpin = ax_price.twinx()

    ax_price.plot(daily_df["date"], daily_df["daily_close"], color="navy", label="Daily Close")
    ax_vpin.plot(
        daily_df["date"],
        daily_df["daily_mean_vpin"],
        color="crimson",
        label="Daily Mean VPIN",
    )
    ax_vpin.plot(
        daily_df["date"],
        daily_df["daily_max_vpin"],
        color="darkorange",
        linestyle="--",
        alpha=0.8,
        label="Daily Max VPIN",
    )

    ax_price.set_title(f"{CONTRACT_LABELS.get(contract, contract)} Price vs VPIN")
    ax_price.set_xlabel("Date")
    ax_price.set_ylabel("Price")
    ax_vpin.set_ylabel("VPIN")
    ax_price.grid(alpha=0.3)

    handles_1, labels_1 = ax_price.get_legend_handles_labels()
    handles_2, labels_2 = ax_vpin.get_legend_handles_labels()
    ax_price.legend(handles_1 + handles_2, labels_1 + labels_2, loc="upper left")

    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_vpin_slope_vs_return(daily_df: pd.DataFrame, output_path: Path, contract: str) -> None:
    """Plot daily VPIN slope against next-day futures return."""
    plot_df = daily_df[["daily_vpin_slope", "future_return"]].dropna()
    if plot_df.empty:
        raise ValueError("Not enough daily observations to plot VPIN slope vs future return.")

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(
        plot_df["daily_vpin_slope"],
        plot_df["future_return"],
        alpha=0.65,
        color="teal",
        edgecolors="none",
    )

    x_values = plot_df["daily_vpin_slope"].to_numpy()
    y_values = plot_df["future_return"].to_numpy()
    if len(plot_df) >= 2 and np.nanstd(x_values) > 0:
        beta_1, beta_0 = np.polyfit(x_values, y_values, deg=1)
        fitted_x = np.linspace(x_values.min(), x_values.max(), 100)
        fitted_y = beta_1 * fitted_x + beta_0
        ax.plot(fitted_x, fitted_y, color="black", linewidth=1.2, linestyle="--")

    correlation = plot_df["daily_vpin_slope"].corr(plot_df["future_return"])
    ax.set_title(
        f"{CONTRACT_LABELS.get(contract, contract)} VPIN Slope vs Next-Day Return\n"
        f"Correlation = {correlation:.3f}"
    )
    ax.set_xlabel("Daily VPIN Slope")
    ax.set_ylabel("Next-Day Return")
    ax.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_strategy_nav(backtest_df: pd.DataFrame, output_path: Path, contract: str) -> None:
    """Plot strategy NAV against the long-only benchmark."""
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(backtest_df["date"], backtest_df["strategy_nav"], label="VPIN Strategy NAV", color="crimson")
    ax.plot(
        backtest_df["date"],
        backtest_df["benchmark_nav"],
        label="Long-Only Benchmark",
        color="navy",
    )
    ax.set_title(f"{CONTRACT_LABELS.get(contract, contract)} Strategy NAV vs Benchmark")
    ax.set_xlabel("Date")
    ax.set_ylabel("Net Asset Value")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left")

    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_drawdown(backtest_df: pd.DataFrame, output_path: Path, contract: str) -> None:
    """Plot drawdown comparison between the strategy and the benchmark."""
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(
        backtest_df["date"],
        backtest_df["strategy_drawdown"],
        label="VPIN Strategy Drawdown",
        color="crimson",
    )
    ax.plot(
        backtest_df["date"],
        backtest_df["benchmark_drawdown"],
        label="Benchmark Drawdown",
        color="navy",
    )
    ax.set_title(f"{CONTRACT_LABELS.get(contract, contract)} Drawdown Comparison")
    ax.set_xlabel("Date")
    ax.set_ylabel("Drawdown")
    ax.grid(alpha=0.3)
    ax.legend(loc="lower left")

    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def save_outputs(
    intraday_vpin: pd.DataFrame,
    daily_signal_df: pd.DataFrame,
    backtest_summary: pd.DataFrame,
    backtest_df: pd.DataFrame,
    processed_dir: Path,
    output_dir: Path,
) -> dict[str, Path]:
    """Persist research tables to the required project folders."""
    processed_dir.mkdir(parents=True, exist_ok=True)
    tables_dir = output_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    intraday_path = processed_dir / "vpin_intraday.csv"
    daily_path = processed_dir / "vpin_daily.csv"
    summary_path = tables_dir / "backtest_summary.csv"
    nav_path = tables_dir / "strategy_nav.csv"

    intraday_output = (
        intraday_vpin[OUTPUT_INTRADAY_COLUMNS]
        .sort_values(["contract", "datetime"])
        .reset_index(drop=True)
    )
    daily_output = (
        daily_signal_df[OUTPUT_DAILY_COLUMNS]
        .sort_values(["contract", "date"])
        .reset_index(drop=True)
    )
    summary_output = (
        backtest_summary.sort_values(["contract", "strategy"]).reset_index(drop=True)
    )
    nav_output = (
        backtest_df[OUTPUT_NAV_COLUMNS]
        .sort_values(["contract", "date"])
        .reset_index(drop=True)
    )

    intraday_output.to_csv(intraday_path, index=False)
    daily_output.to_csv(daily_path, index=False)
    summary_output.to_csv(summary_path, index=False)
    nav_output.to_csv(nav_path, index=False)

    expected_paths = {
        "intraday": intraday_path,
        "daily": daily_path,
        "summary": summary_path,
        "nav": nav_path,
    }
    missing_outputs = [str(path) for path in expected_paths.values() if not path.exists()]
    if missing_outputs:
        raise IOError(f"Failed to generate expected output files: {missing_outputs}")
    return expected_paths


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="VPIN timing research for Chinese government bond futures.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Path to minute-level input data. Only valid when a single contract is selected.",
    )
    parser.add_argument(
        "--contract",
        choices=CONTRACT_CHOICES,
        default="ALL",
        help="Futures contract. Use ALL to run both T and TL together.",
    )
    parser.add_argument("--start-date", default="2024-01-01", help="Optional inclusive start date, e.g. 2024-01-01.")
    parser.add_argument("--output-dir", type=Path, default=Path("results"), help="Directory for figures and tables.")
    parser.add_argument(
        "--processed-dir",
        type=Path,
        default=Path("data/processed"),
        help="Directory for processed intraday and daily VPIN tables.",
    )
    parser.add_argument(
        "--classification-method",
        choices=["bvc", "tick"],
        default="bvc",
        help="Intraday buy/sell volume classification method.",
    )
    parser.add_argument("--classification-window", type=int, default=50, help="Window for BVC volatility scaling.")
    parser.add_argument("--vpin-window", type=int, default=50, help="Rolling window for VPIN.")
    parser.add_argument("--slope-window", type=int, default=10, help="Intraday VPIN slope window.")
    parser.add_argument("--zscore-window", type=int, default=100, help="Intraday VPIN z-score window.")
    parser.add_argument("--percentile-window", type=int, default=100, help="Intraday VPIN percentile window.")
    parser.add_argument("--daily-slope-window", type=int, default=5, help="Daily VPIN slope window.")
    parser.add_argument("--daily-stats-window", type=int, default=60, help="Daily VPIN z-score and percentile window.")
    parser.add_argument(
        "--signal-percentile-threshold",
        type=float,
        default=0.8,
        help="Daily VPIN percentile threshold for defensive positioning.",
    )
    parser.add_argument(
        "--signal-slope-threshold",
        type=float,
        default=0.0,
        help="Daily VPIN slope threshold for defensive positioning.",
    )
    parser.add_argument(
        "--transaction-cost",
        type=float,
        default=0.0,
        help="One-way transaction cost applied to daily turnover.",
    )
    return parser.parse_args()


def resolve_input_path(input_path: Path | None, contract: str) -> Path:
    """Resolve the effective input path."""
    if input_path is not None:
        return input_path

    default_path = DEFAULT_INPUTS.get(contract)
    if default_path is None:
        raise ValueError(f"No default input path is configured for contract {contract}.")
    return default_path


def resolve_contracts(contract: str) -> list[str]:
    """Expand the requested contract selector into a contract list."""
    if contract == "ALL":
        return ["T", "TL"]
    return [contract]


def run_contract_pipeline(
    contract: str,
    input_path: Path,
    args: argparse.Namespace,
    figures_dir: Path,
) -> dict[str, Any]:
    """Run the full VPIN workflow for a single contract."""
    intraday_df = load_intraday_data(input_path=input_path, start_date=args.start_date)
    intraday_vpin = calculate_vpin(
        intraday_df=intraday_df,
        classification_method=args.classification_method,
        classification_window=args.classification_window,
        vpin_window=args.vpin_window,
        slope_window=args.slope_window,
        zscore_window=args.zscore_window,
        percentile_window=args.percentile_window,
    )
    intraday_vpin["contract"] = contract

    daily_vpin = aggregate_vpin_to_daily(
        intraday_vpin=intraday_vpin,
        daily_slope_window=args.daily_slope_window,
        daily_stats_window=args.daily_stats_window,
    )
    daily_signal = generate_vpin_signal(
        daily_vpin=daily_vpin,
        high_percentile_threshold=args.signal_percentile_threshold,
        slope_threshold=args.signal_slope_threshold,
    )
    daily_signal["contract"] = contract

    backtest_df = run_backtest(
        daily_signal_df=daily_signal,
        transaction_cost=args.transaction_cost,
    )
    backtest_df["contract"] = contract
    backtest_summary = calculate_performance_metrics(backtest_df=backtest_df, contract=contract)

    price_vpin_path = figures_dir / f"{contract.lower()}_price_vs_vpin.png"
    slope_return_path = figures_dir / f"{contract.lower()}_vpin_slope_vs_return.png"
    nav_path = figures_dir / f"{contract.lower()}_strategy_nav_vs_benchmark.png"
    drawdown_path = figures_dir / f"{contract.lower()}_drawdown_comparison.png"

    plot_price_and_vpin(daily_signal, price_vpin_path, contract)
    plot_vpin_slope_vs_return(daily_signal, slope_return_path, contract)
    plot_strategy_nav(backtest_df, nav_path, contract)
    plot_drawdown(backtest_df, drawdown_path, contract)

    figure_paths = [price_vpin_path, slope_return_path, nav_path, drawdown_path]
    missing_figures = [str(path) for path in figure_paths if not path.exists()]
    if missing_figures:
        raise IOError(f"Failed to generate expected figure files for {contract}: {missing_figures}")

    return {
        "contract": contract,
        "input_path": input_path,
        "intraday_vpin": intraday_vpin,
        "daily_signal": daily_signal,
        "backtest_df": backtest_df,
        "backtest_summary": backtest_summary,
        "figure_paths": figure_paths,
    }


def main() -> None:
    """Run the end-to-end VPIN research workflow."""
    args = parse_args()
    contracts = resolve_contracts(args.contract)
    if args.input is not None and len(contracts) > 1:
        raise ValueError("`--input` can only be used with a single contract. Use the default files for ALL.")
    figures_dir = args.output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    run_results: list[dict[str, Any]] = []
    for contract in contracts:
        input_path = resolve_input_path(args.input, contract) if len(contracts) == 1 else resolve_input_path(None, contract)
        print(f"Running VPIN workflow for {contract} with input: {input_path}")
        run_results.append(
            run_contract_pipeline(
                contract=contract,
                input_path=input_path,
                args=args,
                figures_dir=figures_dir,
            )
        )

    intraday_vpin = pd.concat(
        [result["intraday_vpin"] for result in run_results],
        axis=0,
        ignore_index=True,
    )
    daily_signal = pd.concat(
        [result["daily_signal"] for result in run_results],
        axis=0,
        ignore_index=True,
    )
    backtest_df = pd.concat(
        [result["backtest_df"] for result in run_results],
        axis=0,
        ignore_index=True,
    )
    backtest_summary = pd.concat(
        [result["backtest_summary"] for result in run_results],
        axis=0,
        ignore_index=True,
    )

    saved_paths = save_outputs(
        intraday_vpin=intraday_vpin,
        daily_signal_df=daily_signal,
        backtest_summary=backtest_summary,
        backtest_df=backtest_df,
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
    )

    expected_figures = [path for result in run_results for path in result["figure_paths"]]
    missing_figures = [str(path) for path in expected_figures if not path.exists()]
    if missing_figures:
        raise IOError(f"Failed to generate expected figure files: {missing_figures}")

    print(f"Contracts: {', '.join(contracts)}")
    for result in run_results:
        input_path = Path(result["input_path"])
        input_mtime = pd.Timestamp(input_path.stat().st_mtime, unit="s")
        print(f"Input file [{result['contract']}]: {input_path} (updated {input_mtime})")
    print("Saved tables:")
    for name, path in saved_paths.items():
        print(f"  {name}: {path}")
    print("Saved figures:")
    for path in expected_figures:
        print(f"  {path}")
    print("Backtest summary:")
    print(backtest_summary.to_string(index=False))


if __name__ == "__main__":
    main()
