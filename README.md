# 基于 VPIN 的中国国债期货择时框架 | VPIN-Based Timing Strategy for Chinese Government Bond Futures

<p align="center">
  <a href="#zh"><img src="https://img.shields.io/badge/LANGUAGE-%E4%B8%AD%E6%96%87-E84D3D?style=for-the-badge&labelColor=3B3F47" alt="LANGUAGE 中文"></a>
  <a href="#en"><img src="https://img.shields.io/badge/LANGUAGE-ENGLISH-2F73C9?style=for-the-badge&labelColor=3B3F47" alt="LANGUAGE ENGLISH"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/Asset-CGB%20Futures-F2C94C?style=for-the-badge" alt="CGB Futures">
  <img src="https://img.shields.io/badge/Strategy-VPIN%20Timing-7AC943?style=for-the-badge" alt="VPIN Timing">
</p>

<a id="zh"></a>

## 简体中文

当前语言：中文 | [Switch to English](#en)

---

### 项目简介

本项目是一个基于 **VPIN（Volume-Synchronized Probability of Informed Trading）** 的中国国债期货 **CTA 风格空头风险择时框架**。项目使用分钟级交易数据构建订单流毒性指标，并检验 VPIN 对 `T`（10 年国债期货）和 `TL`（30 年国债期货）短周期空头风险识别、风险暴露切换与防御择时的解释力。

当前研究逻辑专注于 VPIN：当订单流毒性升高且 VPIN 斜率走强时，策略将其视为潜在的交易性空头/下行风险信号，并从多头暴露切换到空仓防御状态。当前实现是多头 / 空仓版本的 CTA 择时原型，并不直接建立期货空头头寸，也不包含均线、动量、波动率、RSRS、MACD、RSI、布林带等非 VPIN 策略。

### VPIN 指标解释

VPIN = **Volume-Synchronized Probability of Informed Trading**，即知情交易概率。该指标由 David Easley、Maureen O'Hara 以及 Marcos M. López de Prado 等提出，用于捕捉市场微观结构恶化、订单流毒性和流动性枯竭风险。

与传统基于日历时间等距采样的方法不同，VPIN 引入“等量桶”（Volume Buckets）概念，将连续交易数据按照固定成交量进行切分，从而降低高频数据中的波动率聚集影响，更接近真实交易节奏。

VPIN 衡量的是一段时间内买卖成交量失衡程度。若买卖量长期失衡，说明订单流可能更具毒性，市场可能面临信息交易压力、流动性恶化或价格跳变风险。

$$
VPIN = \frac{\sum_{\tau=1}^{n} |V_{\tau}^{S} - V_{\tau}^{B}|}{nV}
$$

其中：

| 符号 | 含义 |
| --- | --- |
| $V_{\tau}^{B}$ | 第 $\tau$ 个等量桶内估计的买入成交量 |
| $V_{\tau}^{S}$ | 第 $\tau$ 个等量桶内估计的卖出成交量 |
| $V$ | 单个等量桶的固定成交量 |
| $n$ | 滚动窗口内的等量桶数量 |

在中国国债期货 `T` / `TL` 合约中，VPIN 可以被理解为订单流毒性或交易拥挤程度的代理变量。当 VPIN 快速上升时，可能意味着市场交易方向更加单边，未来短期价格波动或回撤风险上升。因此，本项目使用“高 VPIN + VPIN slope 为正”作为降低多头仓位的风险预警条件。

### 核心功能

- 分钟级国债期货数据读取与标准化；
- VPIN 指标计算；
- 日频 VPIN 特征聚合；
- VPIN 空头风险 / 防御择时信号生成；
- CTA 风格多头 / 空仓切换策略回测；
- 绩效指标统计；
- 可视化输出。

### 方法框架

主脚本 `vpin_timing.py` 使用分钟级数据（优先 5 分钟）完成以下流程：

1. 读取并标准化分钟级行情数据；
2. 使用价格变化方向或 Bulk Volume Classification 近似拆分买量和卖量；
3. 计算分钟级 VPIN、VPIN slope、z-score 和 percentile；
4. 将 VPIN 特征聚合到日频；
5. 根据日频 VPIN 分位数和斜率生成空头风险 / 防御择时信号；
6. 使用日频 close-to-close 收益回测 CTA 风格多头 / 空仓切换策略；
7. 输出净值、绩效指标和图表。

为避免未来函数，交易仓位使用：

```python
position = signal_raw.shift(1)
```

即所有信号严格滞后 1 个交易日执行。

### 仓库结构

当前仓库结构以实际文件为准：

```text
.
├── LICENSE
├── README.md
├── requirements.txt
├── market_data.py
├── update_market_data.py
├── vpin_timing.py
├── data/
│   ├── raw/
│   │   ├── tushare/
│   │   └── akshare/
│   ├── canonical/
│   │   ├── T_5min.parquet
│   │   └── TL_5min.parquet
│   ├── metadata/
│   │   ├── contract_mapping.parquet
│   │   └── latest_update.json
│   └── processed/
│       ├── vpin_intraday.csv
│       └── vpin_daily.csv
├── results/
│   ├── report.md
│   ├── tables/
│   │   ├── backtest_summary.csv
│   │   └── strategy_nav.csv
│   └── figures/
│       ├── t_price_vs_vpin.png
│       ├── t_vpin_slope_vs_return.png
│       ├── t_strategy_nav_vs_benchmark.png
│       ├── t_drawdown_comparison.png
│       ├── tl_price_vs_vpin.png
│       ├── tl_vpin_slope_vs_return.png
│       ├── tl_strategy_nav_vs_benchmark.png
│       └── tl_drawdown_comparison.png
└── report/
    └── *.pdf
```

说明：

- `update_market_data.py` 使用 Tushare 和 AKShare 重建可审计的主力连续5分钟数据；
- Tushare是规范主数据，AKShare用于同一真实合约的交叉核验和精确缺口补充；
- 原始数据、主力映射和规范研究输入均不使用 Excel；
- `data/processed/`、`results/tables/` 和 `results/figures/` 中的文件为当前已有 pipeline 输出；
- `results/report.md` 是正式双语研究报告；
- `LICENSE` 声明本项目采用 MIT 协议。

### 输入数据格式

输入文件支持 `parquet`、`csv`，标准字段为：

- `datetime`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `open_interest`

脚本兼容以下常见别名：

- `time` / `date` / `timestamp` / `时间` → `datetime`
- `oi` / `持仓量` → `open_interest`
- `vol` / `成交量` → `volume`

仓库默认输入文件：

- `data/canonical/T_5min.parquet`
- `data/canonical/TL_5min.parquet`

规范 Parquet 还保留 `source_contract`、`source` 和 `roll_flag`，用于审计真实月合约、数据来源与换月点。VPIN滚动状态在真实合约切换时重置，换月日的跨合约价差不计入日收益。

### 输出文件

表格输出：

- `data/processed/vpin_intraday.csv`
- `data/processed/vpin_daily.csv`
- `results/tables/backtest_summary.csv`
- `results/tables/strategy_nav.csv`

图表输出：

- `results/figures/t_price_vs_vpin.png`
- `results/figures/t_vpin_slope_vs_return.png`
- `results/figures/t_strategy_nav_vs_benchmark.png`
- `results/figures/t_drawdown_comparison.png`
- `results/figures/tl_price_vs_vpin.png`
- `results/figures/tl_vpin_slope_vs_return.png`
- `results/figures/tl_strategy_nav_vs_benchmark.png`
- `results/figures/tl_drawdown_comparison.png`

### 已有回测结果

<!-- AUTO-DATE-RANGE-ZH -->
以下结果来自当前仓库中的 `results/tables/backtest_summary.csv`。T覆盖 **2015-03-20 至 2026-07-27**，TL覆盖 **2023-04-21 至 2026-07-27**。
<!-- /AUTO-DATE-RANGE-ZH -->

<!-- AUTO-TABLE-ZH -->
| 合约 | 策略 | 累计收益 | 年化收益 | 年化波动率 | 夏普比率 | 最大回撤 | Calmar | 胜率 | 换手率 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| T | vpin_strategy | 0.149933 | 0.012865 | 0.032221 | 0.399285 | 0.067382 | 0.190932 | 0.416848 | 0.287945 |
| T | long_only_benchmark | 0.272923 | 0.022327 | 0.035258 | 0.633233 | 0.073460 | 0.303933 | 0.518155 | 0.000000 |
| TL | vpin_strategy | 0.110943 | 0.034130 | 0.057921 | 0.589250 | 0.070108 | 0.486819 | 0.440506 | 0.289873 |
| TL | long_only_benchmark | 0.211858 | 0.063213 | 0.063197 | 1.000250 | 0.091549 | 0.690474 | 0.558228 | 0.000000 |
<!-- /AUTO-TABLE-ZH -->

### 结果图表

#### T 合约

<p align="center">
  <img src="results/figures/t_price_vs_vpin.png" alt="T Price vs VPIN" width="48%">
  <img src="results/figures/t_strategy_nav_vs_benchmark.png" alt="T Strategy NAV vs Benchmark" width="48%">
</p>

<p align="center">
  <img src="results/figures/t_vpin_slope_vs_return.png" alt="T VPIN Slope vs Return" width="48%">
  <img src="results/figures/t_drawdown_comparison.png" alt="T Drawdown Comparison" width="48%">
</p>

#### TL 合约

<p align="center">
  <img src="results/figures/tl_price_vs_vpin.png" alt="TL Price vs VPIN" width="48%">
  <img src="results/figures/tl_strategy_nav_vs_benchmark.png" alt="TL Strategy NAV vs Benchmark" width="48%">
</p>

<p align="center">
  <img src="results/figures/tl_vpin_slope_vs_return.png" alt="TL VPIN Slope vs Return" width="48%">
  <img src="results/figures/tl_drawdown_comparison.png" alt="TL Drawdown Comparison" width="48%">
</p>

### 快速开始

克隆仓库：

```bash
git clone https://github.com/ericxuzhesheng/VPIN-Based-Timing-Strategy-for-Chinese-Government-Bond-Futures.git
cd VPIN-Based-Timing-Strategy-for-Chinese-Government-Bond-Futures
```

安装依赖：

```bash
pip install -r requirements.txt
```

准备数据：

- 在本机设置 `TUSHARE_TOKEN` 环境变量，或通过 `--token-file` 指定仅保存在本机的Token文件；
- 运行 `python update_market_data.py`，同时抓取Tushare和AKShare并生成规范Parquet。

```bash
python update_market_data.py --token-file path/to/tushare_token.txt
```

运行完整 pipeline：

```bash
python vpin_timing.py
```

### 运行命令

运行两个合约：

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

指定起始日期和输出目录：

```bash
python vpin_timing.py --start-date 2024-01-01 --output-dir results --processed-dir data/processed
```

### 主要参数

- `--classification-method`：`bvc` 或 `tick`
- `--classification-window`：BVC 波动率缩放窗口
- `--vpin-window`：VPIN 滚动窗口
- `--slope-window`：分钟级 VPIN slope 窗口
- `--zscore-window`：分钟级 VPIN z-score 窗口
- `--percentile-window`：分钟级 VPIN percentile 窗口
- `--daily-slope-window`：日频 VPIN slope 窗口
- `--daily-stats-window`：日频 z-score / percentile 窗口
- `--signal-percentile-threshold`：高 VPIN 分位阈值
- `--signal-slope-threshold`：VPIN slope 阈值
- `--transaction-cost`：按换手施加的单边交易成本

---

<a id="en"></a>

## English

Current language: English | [切换到中文](#zh)

---

### Project Overview

This repository provides a **VPIN (Volume-Synchronized Probability of Informed Trading)** based **CTA-style short-risk timing framework** for Chinese government bond futures. It uses minute-level trading data to construct order-flow toxicity indicators and evaluates the explanatory power of VPIN for short-horizon short-risk detection, risk-exposure switching, and defensive timing in `T` 10-year and `TL` 30-year government bond futures.

The current research logic focuses only on VPIN: when order-flow toxicity rises and the VPIN slope strengthens, the strategy treats it as a potential trading-oriented short/downside-risk signal and switches from long exposure to a flat defensive state. The current implementation is a long/flat CTA timing prototype; it does not directly open short futures positions and does not include non-VPIN rules such as moving averages, momentum, volatility filters, RSRS, MACD, RSI, or Bollinger Bands.

### VPIN Indicator

VPIN stands for **Volume-Synchronized Probability of Informed Trading**. The indicator was proposed by David Easley, Maureen O'Hara, Marcos M. López de Prado and co-authors to measure market microstructure stress, order-flow toxicity, and the risk of deteriorating liquidity.

Unlike calendar-time sampling, VPIN uses volume buckets: trades are grouped by fixed volume rather than fixed clock intervals. This volume-synchronized view reduces the impact of volatility clustering in high-frequency data and better reflects the market's actual trading rhythm.

VPIN measures buy-sell volume imbalance within rolling volume buckets. Higher VPIN indicates stronger order-flow toxicity and potentially worse liquidity conditions, especially when one-sided trading pressure persists.

$$
VPIN = \frac{\sum_{\tau=1}^{n} |V_{\tau}^{S} - V_{\tau}^{B}|}{nV}
$$

Where:

| Symbol | Definition |
| --- | --- |
| $V_{\tau}^{B}$ | Estimated buy volume in volume bucket $\tau$ |
| $V_{\tau}^{S}$ | Estimated sell volume in volume bucket $\tau$ |
| $V$ | Fixed volume size of each volume bucket |
| $n$ | Number of volume buckets in the rolling VPIN window |

In this project, high VPIN combined with positive VPIN slope is used as a defensive timing signal for Chinese Government Bond Futures. For `T` and `TL`, a rapid VPIN increase is interpreted as a warning that trading flow is becoming more one-sided and that short-term volatility or drawdown risk may rise.

### Core Features

- Minute-level government bond futures data loading and standardization;
- VPIN indicator calculation;
- Daily VPIN feature aggregation;
- VPIN short-risk / defensive timing signal generation;
- CTA-style long/flat switching strategy backtesting;
- Performance metric calculation;
- Visualization output.

### Methodology

The main script `vpin_timing.py` uses minute-level data, preferably 5-minute bars, and runs the following workflow:

1. Load and standardize minute-level market data;
2. Approximate buy and sell volume using price direction or Bulk Volume Classification;
3. Compute intraday VPIN, VPIN slope, z-score, and percentile;
4. Aggregate VPIN features to daily frequency;
5. Generate short-risk / defensive timing signals from daily VPIN percentile and slope;
6. Backtest a CTA-style long/flat switching strategy with daily close-to-close returns;
7. Export NAV series, performance metrics, and figures.

To avoid look-ahead bias, the tradable position is defined as:

```python
position = signal_raw.shift(1)
```

Therefore, every signal is executed with a strict one-trading-day lag.

### Repository Structure

The repository structure below reflects the actual inspected files:

```text
.
├── LICENSE
├── README.md
├── requirements.txt
├── market_data.py
├── update_market_data.py
├── vpin_timing.py
├── data/
│   ├── raw/
│   │   ├── tushare/
│   │   └── akshare/
│   ├── canonical/
│   │   ├── T_5min.parquet
│   │   └── TL_5min.parquet
│   ├── metadata/
│   │   ├── contract_mapping.parquet
│   │   └── latest_update.json
│   └── processed/
│       ├── vpin_intraday.csv
│       └── vpin_daily.csv
├── results/
│   ├── report.md
│   ├── tables/
│   │   ├── backtest_summary.csv
│   │   └── strategy_nav.csv
│   └── figures/
│       ├── t_price_vs_vpin.png
│       ├── t_vpin_slope_vs_return.png
│       ├── t_strategy_nav_vs_benchmark.png
│       ├── t_drawdown_comparison.png
│       ├── tl_price_vs_vpin.png
│       ├── tl_vpin_slope_vs_return.png
│       ├── tl_strategy_nav_vs_benchmark.png
│       └── tl_drawdown_comparison.png
└── report/
    └── *.pdf
```

Notes:

- `update_market_data.py` rebuilds auditable main-contract 5-minute data with Tushare and AKShare;
- Tushare is the canonical source, while AKShare cross-checks identical concrete contracts and fills exact missing bars;
- Raw data, mappings, and canonical research inputs do not use Excel;
- Files under `data/processed/`, `results/tables/`, and `results/figures/` are existing pipeline outputs;
- `results/report.md` is the formal bilingual research report;
- `LICENSE` declares that this project is released under the MIT License.

### Input Data Schema

Supported input formats are `parquet` and `csv`. The standardized columns are:

- `datetime`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `open_interest`

Common aliases are supported automatically:

- `time` / `date` / `timestamp` / `时间` → `datetime`
- `oi` / `持仓量` → `open_interest`
- `vol` / `成交量` → `volume`

Default local input files:

- `data/canonical/T_5min.parquet`
- `data/canonical/TL_5min.parquet`

Canonical Parquet also retains `source_contract`, `source`, and `roll_flag` for concrete-contract, source, and rollover auditing. VPIN state resets at each concrete-contract change, and cross-contract rollover gaps are excluded from daily returns.

### Output Files

Tables:

- `data/processed/vpin_intraday.csv`
- `data/processed/vpin_daily.csv`
- `results/tables/backtest_summary.csv`
- `results/tables/strategy_nav.csv`

Figures:

- `results/figures/t_price_vs_vpin.png`
- `results/figures/t_vpin_slope_vs_return.png`
- `results/figures/t_strategy_nav_vs_benchmark.png`
- `results/figures/t_drawdown_comparison.png`
- `results/figures/tl_price_vs_vpin.png`
- `results/figures/tl_vpin_slope_vs_return.png`
- `results/figures/tl_strategy_nav_vs_benchmark.png`
- `results/figures/tl_drawdown_comparison.png`

### Existing Backtest Results

<!-- AUTO-DATE-RANGE-EN -->
The following results are from `results/tables/backtest_summary.csv`. T covers **2015-03-20 through 2026-07-27**, while TL covers **2023-04-21 through 2026-07-27**.
<!-- /AUTO-DATE-RANGE-EN -->

<!-- AUTO-TABLE-EN -->
| Contract | Strategy | Cumulative Return | Annualized Return | Annualized Volatility | Sharpe Ratio | Max Drawdown | Calmar | Win Rate | Turnover |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| T | vpin_strategy | 0.149933 | 0.012865 | 0.032221 | 0.399285 | 0.067382 | 0.190932 | 0.416848 | 0.287945 |
| T | long_only_benchmark | 0.272923 | 0.022327 | 0.035258 | 0.633233 | 0.073460 | 0.303933 | 0.518155 | 0.000000 |
| TL | vpin_strategy | 0.110943 | 0.034130 | 0.057921 | 0.589250 | 0.070108 | 0.486819 | 0.440506 | 0.289873 |
| TL | long_only_benchmark | 0.211858 | 0.063213 | 0.063197 | 1.000250 | 0.091549 | 0.690474 | 0.558228 | 0.000000 |
<!-- /AUTO-TABLE-EN -->

### Result Figures

#### T Contract

<p align="center">
  <img src="results/figures/t_price_vs_vpin.png" alt="T Price vs VPIN" width="48%">
  <img src="results/figures/t_strategy_nav_vs_benchmark.png" alt="T Strategy NAV vs Benchmark" width="48%">
</p>

<p align="center">
  <img src="results/figures/t_vpin_slope_vs_return.png" alt="T VPIN Slope vs Return" width="48%">
  <img src="results/figures/t_drawdown_comparison.png" alt="T Drawdown Comparison" width="48%">
</p>

#### TL Contract

<p align="center">
  <img src="results/figures/tl_price_vs_vpin.png" alt="TL Price vs VPIN" width="48%">
  <img src="results/figures/tl_strategy_nav_vs_benchmark.png" alt="TL Strategy NAV vs Benchmark" width="48%">
</p>

<p align="center">
  <img src="results/figures/tl_vpin_slope_vs_return.png" alt="TL VPIN Slope vs Return" width="48%">
  <img src="results/figures/tl_drawdown_comparison.png" alt="TL Drawdown Comparison" width="48%">
</p>

### Quick Start

Clone the repository:

```bash
git clone https://github.com/ericxuzhesheng/VPIN-Based-Timing-Strategy-for-Chinese-Government-Bond-Futures.git
cd VPIN-Based-Timing-Strategy-for-Chinese-Government-Bond-Futures
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Prepare data:

- Set `TUSHARE_TOKEN` locally, or pass a local-only token file with `--token-file`;
- Run `python update_market_data.py` to fetch both Tushare and AKShare and build canonical Parquet files.

```bash
python update_market_data.py --token-file path/to/tushare_token.txt
```

Run the full pipeline:

```bash
python vpin_timing.py
```

### Run Commands

Run both contracts:

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

Specify a start date and output directories:

```bash
python vpin_timing.py --start-date 2024-01-01 --output-dir results --processed-dir data/processed
```

### Key Parameters

- `--classification-method`: `bvc` or `tick`
- `--classification-window`: BVC volatility scaling window
- `--vpin-window`: VPIN rolling window
- `--slope-window`: intraday VPIN slope window
- `--zscore-window`: intraday VPIN z-score window
- `--percentile-window`: intraday VPIN percentile window
- `--daily-slope-window`: daily VPIN slope window
- `--daily-stats-window`: daily z-score / percentile window
- `--signal-percentile-threshold`: high-VPIN percentile threshold
- `--signal-slope-threshold`: VPIN slope threshold
- `--transaction-cost`: one-way transaction cost applied to turnover

### References

The core VPIN theory and implementation in this project are based on the following academic literature and research reports (see `report/` directory):

**Foundational Theory:**
1.  **Easley, D., López de Prado, M. M., & O'Hara, M. (2012).** "Flow Toxicity and Liquidity in a High-Frequency World." *The Review of Financial Studies*, 25(5), 1457-1493.
2.  **Easley, D., López de Prado, M. M., & O'Hara, M. (2012).** "The Volume Clock: Insights into the High-Frequency Paradigm." *The Journal of Portfolio Management*, 39(1), 19-29.

**Industry Practice (Chinese):**
1.  **Haitong Securities (2020).** "Stock Selection Factor Series (58): Informed Trading and Lead-Buy/Lead-Sell".
2.  **CMS China (2021).** "High-Frequency Tracking Series 2: Applications of High-Frequency Data Factors".
3.  **GF Securities (2022).** "High-Frequency Data Factor Research Series 6: Factor Research under Information Asymmetry Theory".
4.  **GF Securities (2022).** "High-Frequency Data Factor Research Series 7: Re-discussing Factor Research under Information Asymmetry Theory".
5.  **Zheshang Securities (2026).** "Bond Market Special Research: Daily Chart Updates from a CTA Timing Long-Short Perspective".
