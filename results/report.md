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


### VPIN 指标解释

VPIN = **Volume-Synchronized Probability of Informed Trading**，通常译为知情交易概率。该指标由 David Easley、Maureen O'Hara 以及 Marcos M. López de Prado 等在市场微观结构研究中提出，核心目标是刻画订单流毒性（Order Flow Toxicity）、流动性枯竭风险以及市场微观结构状态恶化。

VPIN 的出发点是：在存在信息不对称的市场中，如果知情交易者持续沿同一方向交易，做市商或流动性提供者会承受更高的逆向选择风险。此时，买卖成交量的不平衡会累积，市场流动性可能下降，价格也更容易出现跳变或短期剧烈波动。

#### Volume Buckets 思想

传统高频研究常按日历时间切分样本，例如每 1 分钟或每 5 分钟形成一个 bar。但市场真实交易节奏并不均匀：活跃时段成交密集，清淡时段成交稀疏。VPIN 引入“等量桶”（Volume Buckets）思想，将连续交易按照固定成交量 $V$ 切分，而不是按照固定时间切分。

这种做法的好处是：

- 每个桶包含相近规模的成交量，更接近真实交易节奏；
- 可以弱化高频数据中的波动率聚集与交易强度不均匀问题；
- 便于在滚动成交量窗口中观察买卖失衡是否持续累积。

#### 标准公式

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

公式分子是滚动窗口内各个等量桶买卖成交量差的绝对值之和，刻画累计成交量失衡；分母 $nV$ 是滚动窗口内总成交量。因此，VPIN 可以理解为滚动成交量窗口内“被买卖失衡解释的成交量比例”。数值越高，说明买卖成交量越不均衡，订单流毒性越强。

#### 金融含义与国债期货语境

在中国国债期货 `T` / `TL` 合约中，VPIN 可以被理解为订单流毒性、交易拥挤程度或潜在流动性压力的代理变量。当 VPIN 快速上升时，可能意味着市场交易方向更加单边，流动性提供者面对更高逆向选择风险，未来短期价格波动或回撤风险可能上升。

本项目将 VPIN 聚合到日频，并观察 `daily_vpin_percentile` 与 `daily_vpin_slope`：当 VPIN 处于较高分位且斜率为正时，策略将其解释为订单流毒性正在上升，并触发降低多头仓位的防御条件。当前实现采用多头 / 空仓切换，而不是直接建立空头头寸。

### 数据与输入

当前仓库默认使用由 Tushare 与 AKShare 重建的规范5分钟 Parquet：

- `data/canonical/T_5min.parquet`
- `data/canonical/TL_5min.parquet`

Tushare提供真实月合约主力映射和规范主数据，AKShare用于同合约同时间的交叉核验与精确缺口补充。脚本支持 `parquet`、`csv`，并将输入字段标准化为：

- `datetime`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `open_interest`

规范数据同时保留 `source_contract`、`source` 和 `roll_flag`。VPIN状态在真实合约切换时重置，跨合约换月价差不计入日收益。

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

### 结果解读

在当前全历史结果中：

- 对 `T` 合约，`vpin_strategy` 的累计收益和夏普比率低于 `long_only_benchmark`，最大回撤由 7.35% 降至 6.74%；
- 对 `TL` 合约，策略同样牺牲了部分收益与夏普比率，但最大回撤由 9.15% 降至 7.01%；
- 因而当前VPIN规则体现的是有限的回撤缓释，而不是相对长期持有的收益增强；结论应结合样本外验证和交易成本继续检验。

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

### VPIN Indicator Interpretation

VPIN stands for **Volume-Synchronized Probability of Informed Trading**. It was proposed by David Easley, Maureen O'Hara, Marcos M. López de Prado and co-authors in the market microstructure literature to measure order-flow toxicity, liquidity-stress risk, and deterioration in market microstructure conditions.

The economic intuition is that informed traders tend to trade persistently in the direction of their private information. When this happens, liquidity providers face higher adverse-selection risk. Persistent buy-sell imbalance can therefore signal that liquidity is becoming more fragile and that prices may be more vulnerable to jumps or short-term volatility bursts.

#### Volume Buckets

Many high-frequency studies sample data by calendar time, such as one-minute or five-minute bars. VPIN instead uses volume buckets: trades are grouped into buckets with a fixed volume size $V$, rather than fixed clock-time intervals. This volume-synchronized sampling scheme is designed to align the measurement window with the market's actual trading rhythm.

The volume-bucket approach has several advantages:

- each bucket contains a comparable amount of traded volume;
- the measurement is less dominated by uneven trading intensity across the day;
- rolling windows can track whether buy-sell imbalance is accumulating across comparable volume units.

#### Standard Formula

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

The numerator sums the absolute buy-sell volume imbalance across rolling volume buckets, while the denominator $nV$ is the total volume in the rolling window. VPIN can therefore be read as the share of recent trading volume explained by directional volume imbalance. A higher value indicates stronger order-flow toxicity and potentially worse liquidity conditions.

#### Interpretation for Chinese Government Bond Futures

For Chinese Government Bond Futures `T` and `TL`, VPIN is used as a proxy for order-flow toxicity, trading crowding, and potential liquidity pressure. A rapid increase in VPIN may suggest that trading has become more one-sided and that short-term volatility or drawdown risk is rising.

This project aggregates VPIN to daily frequency and monitors both `daily_vpin_percentile` and `daily_vpin_slope`. When VPIN is in a high percentile and its slope is positive, the strategy interprets the signal as rising order-flow toxicity and reduces long exposure defensively. The current implementation uses a long/flat switch rather than opening explicit short futures positions.

### Data and Inputs

The repository uses canonical 5-minute Parquet rebuilt from Tushare and AKShare:

- `data/canonical/T_5min.parquet`
- `data/canonical/TL_5min.parquet`

Tushare supplies concrete-contract mappings and canonical bars; AKShare cross-checks identical contract/timestamp observations and fills exact gaps. The script supports `parquet` and `csv` inputs and standardizes columns into:

- `datetime`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `open_interest`

Canonical data also retains `source_contract`, `source`, and `roll_flag`. VPIN state resets at concrete-contract changes, and cross-contract rollover gaps are excluded from daily returns.

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

### Interpretation

Based on the full-history outputs:

- For `T`, the strategy trails the long-only benchmark in cumulative return and Sharpe ratio, while reducing maximum drawdown from 7.35% to 6.74%;
- For `TL`, it also sacrifices return and Sharpe ratio, while reducing maximum drawdown from 9.15% to 7.01%;
- The current VPIN rule therefore shows limited drawdown mitigation rather than return enhancement, and still requires out-of-sample and transaction-cost validation.

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
### 参考文献

**学术奠基：**
1.  **Easley, D., López de Prado, M. M., & O'Hara, M. (2012).** "Flow Toxicity and Liquidity in a High-Frequency World." *The Review of Financial Studies*, 25(5), 1457-1493. (对应仓库 `report/Flow Toxicity and Liquidity in a High-Frequency World.pdf`)
2.  **Easley, D., López de Prado, M. M., & O'Hara, M. (2012).** "The Volume Clock: Insights into the High-Frequency Paradigm." *The Journal of Portfolio Management*, 39(1), 19-29. (对应仓库 `report/The Volume Clock Insights into the High-Frequency Paradigm.pdf`)

**业界实践：**
1.  **海通证券 (2020).** 《选股因子系列研究（五十八）：知情交易与主买主卖》. (对应仓库 `report/20200214-海通证券-选股因子系列研究（五十八）：知情交易与主买主卖.pdf`)
2.  **招商证券 (2021).** 《“高频寻踪”系列之二：轻装上阵，高频数据因子的应用》. (对应仓库 `report/20210107-招商证券-“高频寻踪”系列之二：轻装上阵，高频数据因子的应用.pdf`)
3.  **广发证券 (2022).** 《高频数据因子研究系列六：信息不对称理论下的因子研究》. (对应仓库 `report/20220221-广发证券-高频数据因子研究系列六：信息不对称理论下的因子研究.pdf`)
4.  **广发证券 (2022).** 《高频数据因子研究系列七：再谈信息不对称理论下的因子研究》. (对应仓库 `report/20220330-广发证券-高频数据因子研究系列七：再谈信息不对称理论下的因子研究.pdf`)
5.  **浙商证券 (2026).** 《债市专题研究：交易性择时多空视角下每日一图更新》. (对应仓库 `report/浙商证券_债市专题研究_交易性择时多空视角下每日一图更新_20260225.pdf`)

---
