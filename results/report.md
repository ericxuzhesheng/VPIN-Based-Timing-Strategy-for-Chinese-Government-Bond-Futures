# 基于 VPIN 的中国国债期货择时研究报告 | VPIN-Based Timing Strategy for Chinese Government Bond Futures

<a id="zh"></a>

## 简体中文

当前语言：中文 | [Switch to English](#en)

---

### 摘要

本报告基于当前仓库中已有的 `vpin_timing.py` 研究 pipeline 和真实输出文件，整理 VPIN 在中国国债期货短周期择时中的研究框架、数据处理流程、信号逻辑、回测结果与图表索引。报告仅引用当前仓库内已经存在的输出文件，不额外编造任何未生成的回测结果。

研究对象包括：

- `T`：10 年国债期货；
- `TL`：30 年国债期货。

### 研究目标

本项目旨在检验 **VPIN（Volume-Synchronized Probability of Informed Trading）** 所刻画的订单流毒性变化，是否能够为中国国债期货的短周期择时提供解释力。核心问题包括：

1. 分钟级交易数据能否被稳定标准化并用于订单流毒性估计；
2. VPIN 及其日频聚合特征是否能捕捉流动性压力或信息不对称变化；
3. 基于 VPIN 分位数和斜率构造的防御信号，是否能改善不同期限国债期货的回撤或风险收益特征。

### 数据与输入

当前仓库默认使用以下本地分钟级数据文件：

- `10年国债期货_5min_3年.xlsx`
- `30年国债期货_5min_2年.xlsx`

脚本支持 `csv`、`xls`、`xlsx`，并将输入字段标准化为：

- `datetime`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `open_interest`

当前已有处理后数据：

- `data/processed/vpin_intraday.csv`
- `data/processed/vpin_daily.csv`

### 方法说明

#### 1. 分钟级数据标准化

`vpin_timing.py` 首先读取分钟级行情数据，并通过字段别名映射将中文或英文列名统一到标准研究字段。脚本会解析时间、转换数值字段、删除无效行、去重并按时间排序。

#### 2. 买卖量近似拆分

脚本支持两种成交量分类方式：

- `bvc`：Bulk Volume Classification，根据价格变化与滚动波动率估计买量比例；
- `tick`：根据价格变化方向进行简化分类。

拆分后得到：

- `buy_volume`
- `sell_volume`
- `volume_imbalance`

#### 3. VPIN 指标计算

分钟级 VPIN 使用滚动成交量不平衡占滚动总成交量的比例估计，并进一步计算：

- `rolling_vpin`
- `vpin_slope`
- `vpin_zscore`
- `vpin_percentile`

#### 4. 日频聚合

分钟级结果按交易日聚合，生成日频研究表。核心字段包括：

- `daily_close`
- `daily_return`
- `daily_mean_vpin`
- `daily_max_vpin`
- `daily_vpin_slope`
- `daily_vpin_zscore`
- `daily_vpin_percentile`
- `future_return`

#### 5. 信号生成

当前策略为多头 / 防御切换模型：当 `daily_vpin_percentile` 处于高分位且 `daily_vpin_slope` 为正时，认为订单流毒性上升，策略切换到防御状态；其余情况下维持正常多头仓位。

为避免未来函数，实际交易仓位使用滞后信号：

```python
position = signal_raw.shift(1)
```

#### 6. 回测设定

回测使用日频 close-to-close 收益，比较：

- `vpin_strategy`：VPIN 择时策略；
- `long_only_benchmark`：长期持有基准。

绩效指标包括：

- 累计收益；
- 年化收益；
- 年化波动率；
- 夏普比率；
- 最大回撤；
- Calmar 比率；
- 胜率；
- 换手率。

### 真实回测结果

以下结果来自当前仓库中的 `results/tables/backtest_summary.csv`。

| 合约 | 策略 | 累计收益 | 年化收益 | 年化波动率 | 夏普比率 | 最大回撤 | Calmar | 胜率 | 换手率 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| T | long_only_benchmark | 0.088304 | 0.026710 | 0.024207 | 1.103373 | 0.022459 | 1.189279 | 0.559951 | 0.000000 |
| T | vpin_strategy | 0.061142 | 0.018658 | 0.022427 | 0.831940 | 0.026380 | 0.707262 | 0.463535 | 0.276885 |
| TL | long_only_benchmark | 0.136346 | 0.058031 | 0.070550 | 0.822552 | 0.095250 | 0.609252 | 0.558669 | 0.000000 |
| TL | vpin_strategy | 0.145706 | 0.061869 | 0.061949 | 0.998711 | 0.072508 | 0.853273 | 0.467601 | 0.245184 |

### 结果解读

在当前已有结果中：

- 对 `T` 合约，`vpin_strategy` 的累计收益和夏普比率低于 `long_only_benchmark`，最大回撤也高于基准；
- 对 `TL` 合约，`vpin_strategy` 的累计收益、年化收益和夏普比率高于 `long_only_benchmark`，最大回撤低于基准；
- 两个合约的 VPIN 策略均产生了明显换手，说明该信号确实触发了多头 / 防御切换，而不是静态持有；
- 当前结果显示 VPIN 对不同期限国债期货的择时效果存在差异，后续需要结合更长样本、参数稳健性和交易成本敏感性进一步检验。

### 图表索引

当前仓库已有以下图表输出：

#### T 合约

- `results/figures/t_price_vs_vpin.png`
- `results/figures/t_vpin_slope_vs_return.png`
- `results/figures/t_strategy_nav_vs_benchmark.png`
- `results/figures/t_drawdown_comparison.png`

#### TL 合约

- `results/figures/tl_price_vs_vpin.png`
- `results/figures/tl_vpin_slope_vs_return.png`
- `results/figures/tl_strategy_nav_vs_benchmark.png`
- `results/figures/tl_drawdown_comparison.png`

### 输出文件索引

- 分钟级 VPIN 表：`data/processed/vpin_intraday.csv`
- 日频 VPIN 表：`data/processed/vpin_daily.csv`
- 回测绩效表：`results/tables/backtest_summary.csv`
- 策略净值表：`results/tables/strategy_nav.csv`

### 复现实验

运行完整 pipeline：

```bash
python vpin_timing.py
```

仅运行 `T`：

```bash
python vpin_timing.py --contract T
```

仅运行 `TL`：

```bash
python vpin_timing.py --contract TL
```

指定自定义输入文件：

```bash
python vpin_timing.py --contract T --input data/raw/T_5min.csv
```

### 局限性与后续工作

1. 当前报告仅基于仓库中已有输出文件，不引入额外未验证结果；
2. 当前策略为简洁的多头 / 防御模型，尚未进行参数网格搜索、样本外检验或组合层面优化；
3. 当前报告未对交易所手续费、滑点和冲击成本进行独立建模，除非运行参数中显式设置 `--transaction-cost`；
4. 后续可扩展滚动样本检验、参数稳定性分析、跨品种组合和风险预算约束。

---

<a id="en"></a>

## English

Current language: English | [切换到中文](#zh)

---

### Abstract

This report summarizes the VPIN research pipeline, data processing workflow, signal logic, backtest results, and figure index based on the existing `vpin_timing.py` script and real output files in the current repository. It only cites artifacts that already exist in the repository and does not fabricate any ungenerated performance results.

The research universe includes:

- `T`: 10-year Chinese government bond futures;
- `TL`: 30-year Chinese government bond futures.

### Research Objective

The project evaluates whether **VPIN (Volume-Synchronized Probability of Informed Trading)**, as an order-flow toxicity measure, can provide explanatory power for short-horizon timing in Chinese government bond futures. The core questions are:

1. Whether minute-level trading data can be standardized reliably for order-flow toxicity estimation;
2. Whether VPIN and its daily aggregated features capture liquidity pressure or information asymmetry;
3. Whether a defensive timing signal based on VPIN percentile and slope can improve drawdown or risk-adjusted performance across different government bond futures tenors.

### Data and Inputs

The current repository uses the following default local minute-level files:

- `10年国债期货_5min_3年.xlsx`
- `30年国债期货_5min_2年.xlsx`

The script supports `csv`, `xls`, and `xlsx` inputs and standardizes columns into:

- `datetime`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `open_interest`

Existing processed data files:

- `data/processed/vpin_intraday.csv`
- `data/processed/vpin_daily.csv`

### Methodology

#### 1. Minute-Level Data Standardization

`vpin_timing.py` reads minute-level market data and maps Chinese or English column aliases into a standard research schema. It parses timestamps, converts numeric fields, drops invalid rows, removes duplicate timestamps, and sorts observations chronologically.

#### 2. Buy/Sell Volume Approximation

The script supports two volume classification methods:

- `bvc`: Bulk Volume Classification, which estimates the buy-volume ratio from price changes scaled by rolling volatility;
- `tick`: a simplified classification based on the direction of price changes.

The resulting fields include:

- `buy_volume`
- `sell_volume`
- `volume_imbalance`

#### 3. VPIN Calculation

Intraday VPIN is estimated as rolling volume imbalance divided by rolling total volume. The script also computes:

- `rolling_vpin`
- `vpin_slope`
- `vpin_zscore`
- `vpin_percentile`

#### 4. Daily Aggregation

Intraday results are aggregated by trading day into a daily research table. Core fields include:

- `daily_close`
- `daily_return`
- `daily_mean_vpin`
- `daily_max_vpin`
- `daily_vpin_slope`
- `daily_vpin_zscore`
- `daily_vpin_percentile`
- `future_return`

#### 5. Signal Generation

The current strategy is a long-versus-defensive switching model. When `daily_vpin_percentile` is high and `daily_vpin_slope` is positive, order-flow toxicity is treated as rising and the strategy switches to a defensive position. Otherwise, it keeps normal long exposure.

To avoid look-ahead bias, the tradable position uses a lagged signal:

```python
position = signal_raw.shift(1)
```

#### 6. Backtest Setup

The backtest uses daily close-to-close returns and compares:

- `vpin_strategy`: the VPIN timing strategy;
- `long_only_benchmark`: the long-only benchmark.

Performance metrics include:

- cumulative return;
- annualized return;
- annualized volatility;
- Sharpe ratio;
- maximum drawdown;
- Calmar ratio;
- win rate;
- turnover.

### Real Backtest Results

The following results are from the existing `results/tables/backtest_summary.csv` file.

| Contract | Strategy | Cumulative Return | Annualized Return | Annualized Volatility | Sharpe Ratio | Max Drawdown | Calmar | Win Rate | Turnover |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| T | long_only_benchmark | 0.088304 | 0.026710 | 0.024207 | 1.103373 | 0.022459 | 1.189279 | 0.559951 | 0.000000 |
| T | vpin_strategy | 0.061142 | 0.018658 | 0.022427 | 0.831940 | 0.026380 | 0.707262 | 0.463535 | 0.276885 |
| TL | long_only_benchmark | 0.136346 | 0.058031 | 0.070550 | 0.822552 | 0.095250 | 0.609252 | 0.558669 | 0.000000 |
| TL | vpin_strategy | 0.145706 | 0.061869 | 0.061949 | 0.998711 | 0.072508 | 0.853273 | 0.467601 | 0.245184 |

### Interpretation

Based on the existing outputs:

- For `T`, `vpin_strategy` has lower cumulative return and Sharpe ratio than `long_only_benchmark`, and its maximum drawdown is higher;
- For `TL`, `vpin_strategy` has higher cumulative return, annualized return, and Sharpe ratio than `long_only_benchmark`, while its maximum drawdown is lower;
- The VPIN strategy generates non-zero turnover for both contracts, indicating that the signal actively switches between long and defensive states rather than behaving like static buy-and-hold;
- The current results suggest that VPIN timing effects differ across tenors, and further validation should use longer samples, parameter robustness checks, and transaction-cost sensitivity analysis.

### Figure Index

The repository currently contains the following figures:

#### T Contract

- `results/figures/t_price_vs_vpin.png`
- `results/figures/t_vpin_slope_vs_return.png`
- `results/figures/t_strategy_nav_vs_benchmark.png`
- `results/figures/t_drawdown_comparison.png`

#### TL Contract

- `results/figures/tl_price_vs_vpin.png`
- `results/figures/tl_vpin_slope_vs_return.png`
- `results/figures/tl_strategy_nav_vs_benchmark.png`
- `results/figures/tl_drawdown_comparison.png`

### Output File Index

- Intraday VPIN table: `data/processed/vpin_intraday.csv`
- Daily VPIN table: `data/processed/vpin_daily.csv`
- Backtest summary table: `results/tables/backtest_summary.csv`
- Strategy NAV table: `results/tables/strategy_nav.csv`

### Reproduction

Run the full pipeline:

```bash
python vpin_timing.py
```

Run only `T`:

```bash
python vpin_timing.py --contract T
```

Run only `TL`:

```bash
python vpin_timing.py --contract TL
```

Use a custom input file:

```bash
python vpin_timing.py --contract T --input data/raw/T_5min.csv
```

### Limitations and Next Steps

1. This report only uses existing repository outputs and does not introduce additional unverified results;
2. The current strategy is a simple long-versus-defensive model and has not yet been tested with parameter grid search, out-of-sample validation, or portfolio-level optimization;
3. Exchange fees, slippage, and market impact are not separately modeled unless `--transaction-cost` is explicitly set when running the script;
4. Future extensions can include rolling-window validation, parameter stability analysis, cross-instrument portfolios, and risk-budget constraints.
