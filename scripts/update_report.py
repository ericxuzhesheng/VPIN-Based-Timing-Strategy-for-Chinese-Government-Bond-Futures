"""Update README.md and results/report.md with the latest backtest results.

Reads pipeline outputs and replaces content between HTML comment markers
in both files. Only touches marked regions --- the rest is left unchanged.

Markers in README.md and report.md:
    <!-- AUTO-DATE-RANGE-ZH --> ... <!-- /AUTO-DATE-RANGE-ZH -->
    <!-- AUTO-TABLE-ZH --> ... <!-- /AUTO-TABLE-ZH -->
    <!-- AUTO-DATE-RANGE-EN --> ... <!-- /AUTO-DATE-RANGE-EN -->
    <!-- AUTO-TABLE-EN --> ... <!-- /AUTO-TABLE-EN -->
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
README_PATH = REPO_ROOT / "README.md"
REPORT_PATH = REPO_ROOT / "results" / "report.md"
SUMMARY_PATH = REPO_ROOT / "results" / "tables" / "backtest_summary.csv"
NAV_PATH = REPO_ROOT / "results" / "tables" / "strategy_nav.csv"

# Files that should be kept up-to-date automatically
WATCHED_FILES = [README_PATH, REPORT_PATH]

CONTRACT_PAIRS: list[tuple[str, str]] = [
    ("T", "vpin_strategy"),
    ("T", "long_only_benchmark"),
    ("TL", "vpin_strategy"),
    ("TL", "long_only_benchmark"),
]


def _contract_date_range(nav: pd.DataFrame, contract: str) -> tuple[str, str]:
    """Return (start_date, end_date) as ISO strings for a contract."""
    subset = nav.loc[nav["contract"] == contract, "date"]
    dates = pd.to_datetime(subset, format="%Y-%m-%d", errors="coerce").dropna()
    return dates.min().strftime("%Y-%m-%d"), dates.max().strftime("%Y-%m-%d")


def _format_row(contract: str, strategy: str, row: pd.Series) -> str:
    """Format one markdown table row."""
    cols = [
        contract,
        strategy,
        f"{row['cumulative_return']:.6f}",
        f"{row['annualized_return']:.6f}",
        f"{row['annualized_volatility']:.6f}",
        f"{row['sharpe_ratio']:.6f}",
        f"{row['max_drawdown']:.6f}",
        f"{row['calmar_ratio']:.6f}",
        f"{row['win_rate']:.6f}",
        f"{row['turnover']:.6f}",
    ]
    return "| " + " | ".join(cols) + " |"


def _build_zh_date_line(nav: pd.DataFrame) -> str:
    t_start, t_end = _contract_date_range(nav, "T")
    tl_start, tl_end = _contract_date_range(nav, "TL")
    return (
        f"以下结果来自当前仓库中的 `results/tables/backtest_summary.csv`。"
        f"T覆盖 **{t_start} 至 {t_end}**，TL覆盖 **{tl_start} 至 {tl_end}**。"
    )


def _build_en_date_line(nav: pd.DataFrame) -> str:
    t_start, t_end = _contract_date_range(nav, "T")
    tl_start, tl_end = _contract_date_range(nav, "TL")
    return (
        f"The following results are from `results/tables/backtest_summary.csv`. "
        f"T covers **{t_start} through {t_end}**, "
        f"while TL covers **{tl_start} through {tl_end}**."
    )


TABLE_HEADER_ZH = (
    "| 合约 | 策略 | 累计收益 | 年化收益 | 年化波动率 | 夏普比率 | 最大回撤 | Calmar | 胜率 | 换手率 |"
)
TABLE_SEP_ZH = "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"

TABLE_HEADER_EN = (
    "| Contract | Strategy | Cumulative Return | Annualized Return | "
    "Annualized Volatility | Sharpe Ratio | Max Drawdown | Calmar | "
    "Win Rate | Turnover |"
)
TABLE_SEP_EN = "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"


def _build_table(summary: pd.DataFrame) -> tuple[str, str]:
    """Build Chinese and English markdown tables from backtest data.

    Returns (zh_table, en_table): two strings without date lines.
    """
    rows = []
    for contract, strategy in CONTRACT_PAIRS:
        match = summary.loc[
            (summary["contract"] == contract) & (summary["strategy"] == strategy)
        ]
        if match.empty:
            raise ValueError(
                f"Missing row for {contract}/{strategy} in backtest_summary.csv"
            )
        rows.append(_format_row(contract, strategy, match.iloc[0]))

    zh_rows = "\n".join([TABLE_HEADER_ZH, TABLE_SEP_ZH] + rows)
    en_rows = "\n".join([TABLE_HEADER_EN, TABLE_SEP_EN] + rows)
    return zh_rows, en_rows


def _replace_block(
    text: str,
    open_marker: str,
    close_marker: str,
    replacement: str,
) -> str:
    """Replace content between open_marker and close_marker with replacement."""
    o = text.find(open_marker)
    c = text.find(close_marker)
    if o == -1 or c == -1 or o >= c:
        raise ValueError(
            f"Markers not found: {open_marker} ... {close_marker}"
        )
    before = text[: o + len(open_marker)]
    after = text[c:]
    return before + "\n" + replacement + "\n" + after


def _update_file(
    path: Path,
    zh_date_line: str,
    en_date_line: str,
    zh_table: str,
    en_table: str,
) -> None:
    """Update all 4 auto-blocks in one file."""
    text = path.read_text(encoding="utf-8")

    text = _replace_block(
        text,
        "<!-- AUTO-DATE-RANGE-ZH -->",
        "<!-- /AUTO-DATE-RANGE-ZH -->",
        zh_date_line,
    )
    text = _replace_block(
        text,
        "<!-- AUTO-TABLE-ZH -->",
        "<!-- /AUTO-TABLE-ZH -->",
        zh_table,
    )
    text = _replace_block(
        text,
        "<!-- AUTO-DATE-RANGE-EN -->",
        "<!-- /AUTO-DATE-RANGE-EN -->",
        en_date_line,
    )
    text = _replace_block(
        text,
        "<!-- AUTO-TABLE-EN -->",
        "<!-- /AUTO-TABLE-EN -->",
        en_table,
    )

    path.write_text(text, encoding="utf-8")


def main() -> None:
    summary = pd.read_csv(SUMMARY_PATH)
    nav = pd.read_csv(NAV_PATH)

    zh_date_line = _build_zh_date_line(nav)
    en_date_line = _build_en_date_line(nav)
    zh_table, en_table = _build_table(summary)

    for path in WATCHED_FILES:
        _update_file(path, zh_date_line, en_date_line, zh_table, en_table)
        print(f"Updated {path}")


if __name__ == "__main__":
    main()
