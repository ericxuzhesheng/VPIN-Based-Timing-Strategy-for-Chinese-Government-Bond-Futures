"""Causal, fixed-volume VPIN research on concrete Tushare futures contracts.

Minute BVC is an estimated buy/sell allocation, not observed trade direction.
See results/minute_vpin/protocol.md for the frozen selection and fill protocol.
"""
from __future__ import annotations

import argparse
from collections import deque
from itertools import product
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import ndtr

PRODUCTS = ('TS', 'TF', 'T', 'TL')
GRID = tuple(product((25, 50), (20, 50), (0.8, 0.9)))
COSTS_BP = (0, 1, 3)


def read_input(path: Path, calendar: pd.DatetimeIndex) -> tuple[pd.DataFrame, dict]:
    raw = pd.read_parquet(path).copy()
    required = {'datetime', 'open', 'high', 'low', 'close', 'volume',
                'source_contract', 'source', 'session_complete'}
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f'{path}: missing required fields {sorted(missing)}')
    raw['datetime'] = pd.to_datetime(raw['datetime'])
    raw['date'] = raw.datetime.dt.normalize()
    if raw.datetime.duplicated().any() or not raw.datetime.is_monotonic_increasing:
        raise ValueError(f'{path}: duplicated or unsorted minute timestamps')
    if not raw.source.eq('tushare').all():
        raise ValueError(f'{path}: research source must be Tushare only')
    numbers = raw[['open', 'high', 'low', 'close', 'volume']].to_numpy(float)
    if not np.isfinite(numbers).all() or (numbers[:, :4] <= 0).any() or (numbers[:, 4] < 0).any():
        raise ValueError(f'{path}: non-finite or non-positive prices/negative volume')
    if (raw.high < raw[['open', 'low', 'close']].max(axis=1)).any() or (raw.low > raw[['open', 'high', 'close']].min(axis=1)).any():
        raise ValueError(f'{path}: invalid OHLC envelope')
    day = raw.groupby('date', sort=True).agg(complete=('session_complete', 'all'),
        source_contract=('source_contract', 'first'), contracts=('source_contract', 'nunique'),
        rows=('datetime', 'size'))
    if day.contracts.ne(1).any() or not day.index.isin(calendar).all():
        raise ValueError(f'{path}: multiple contracts per day or non-calendar trading dates')
    complete = day.index[day.complete]
    df = raw.loc[raw.date.isin(complete)].copy().reset_index(drop=True)
    if df.empty:
        raise ValueError(f'{path}: no complete sessions')
    quality = dict(rows=len(raw), complete_rows=len(df), observed_days=len(day),
        complete_days=len(complete), incomplete_days=int((~day.complete).sum()),
        missing_open_days=int(len(calendar[(calendar >= day.index.min()) & (calendar <= day.index.max())].difference(day.index))),
        first_datetime=str(df.datetime.iloc[0]), last_datetime=str(df.datetime.iloc[-1]),
        zero_volume_bars=int(df.volume.eq(0).sum()),
        contracts=int(df.source_contract.nunique()))
    return df, quality


def prepare_segments(df: pd.DataFrame, calendar: pd.DatetimeIndex,
                     adv_window: int = 20, sigma_window: int = 200,
                     sigma_minimum: int = 50) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calibrate only from past full days and reset at each contiguous contract change."""
    result = df.copy()
    daily = result.groupby('date', sort=True).agg(volume=('volume', 'sum'),
        source_contract=('source_contract', 'first'))
    ordinal = pd.Series(np.arange(len(calendar)), index=calendar)
    daily['day_ordinal'] = ordinal.reindex(daily.index).to_numpy()
    daily['segment'] = ((daily.source_contract != daily.source_contract.shift()) |
                         daily.day_ordinal.diff().ne(1)).cumsum()
    # Missing exchange-open days appear as NaN and invalidate trailing ADV calibration.
    daily['past_adv'] = daily.volume.reindex(calendar).rolling(adv_window, min_periods=adv_window).mean().shift(1).reindex(daily.index)
    result['segment'] = result.date.map(daily.segment)
    result['buy_ratio'] = np.nan
    calibration = []
    for segment, group in result.groupby('segment', sort=True):
        days = daily.loc[daily.segment.eq(segment)]
        available = days.loc[days.past_adv.gt(0)]
        if available.empty:
            calibration.append(dict(segment=int(segment), source_contract=group.source_contract.iloc[0],
                calibration_date=None, past_adv=None))
            continue
        first = available.index[0]
        adv = float(available.past_adv.iloc[0])
        indices = group.index[group.date >= first]
        active = result.loc[indices]
        # Do not classify an overnight or cross-contract gap as directional minute flow.
        delta = active.groupby('date', sort=False).close.diff()
        first_bar = delta.isna()
        delta.loc[first_bar] = active.loc[first_bar, 'close'] - active.loc[first_bar, 'open']
        sigma = delta.rolling(sigma_window, min_periods=sigma_minimum).std().shift(1)
        ratio = pd.Series(ndtr((delta / sigma.replace(0, np.nan)).to_numpy()), index=indices)
        ratio.loc[sigma.eq(0)] = 0.5
        result.loc[indices, 'buy_ratio'] = ratio
        calibration.append(dict(segment=int(segment), source_contract=group.source_contract.iloc[0],
            calibration_date=str(first.date()), past_adv=adv))
    return result, pd.DataFrame(calibration)


def equal_volume_buckets(volume: np.ndarray, buy_ratio: np.ndarray,
                         timestamps: np.ndarray, size: float) -> pd.DataFrame:
    """Allocate fractional bars exactly; publish only fully completed fixed-size buckets."""
    volume = np.asarray(volume, dtype=float)
    buy_ratio = np.asarray(buy_ratio, dtype=float)
    if size <= 0 or not np.isfinite(size):
        raise ValueError('bucket size must be finite and positive')
    if len(volume) != len(buy_ratio) or len(volume) != len(timestamps):
        raise ValueError('bucket inputs must have equal lengths')
    if not np.isfinite(volume).all() or not np.isfinite(buy_ratio).all() or (volume < 0).any() or ((buy_ratio < 0) | (buy_ratio > 1)).any():
        raise ValueError('invalid volume or buy ratio')
    positive = volume > 0
    volume, buy_ratio, timestamps = volume[positive], buy_ratio[positive], np.asarray(timestamps)[positive]
    columns = ['completed_at', 'bucket_number', 'bucket_size', 'buy_volume', 'sell_volume', 'imbalance']
    if not len(volume):
        return pd.DataFrame(columns=columns)
    total = np.cumsum(volume)
    cumulative_buy = np.r_[0.0, np.cumsum(volume * buy_ratio)]
    count = int(np.floor(total[-1] / size + 1e-12))
    if count == 0:
        return pd.DataFrame(columns=columns)
    boundary = np.arange(1, count + 1, dtype=float) * size
    at_buy = np.interp(boundary, np.r_[0.0, total], cumulative_buy)
    buy = np.diff(np.r_[0.0, at_buy])
    buy = np.clip(buy, 0.0, size)  # Floating point subtraction only, no economic clipping.
    sell = size - buy
    completed = np.searchsorted(total, boundary, side='left').clip(max=len(total)-1)
    return pd.DataFrame(dict(completed_at=pd.to_datetime(timestamps[completed]),
        bucket_number=np.arange(1, count + 1), bucket_size=size,
        buy_volume=buy, sell_volume=sell, imbalance=np.abs(buy - sell) / size))


def build_buckets(prepared: pd.DataFrame, calibration: pd.DataFrame, divisor: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    tables, audits = [], []
    for row in calibration.to_dict('records'):
        group = prepared.loc[prepared.segment.eq(row['segment'])]
        eligible = group.loc[group.buy_ratio.notna() & group.volume.gt(0)]
        if pd.isna(row['past_adv']) or eligible.empty:
            size, buckets = np.nan, pd.DataFrame()
        else:
            size = row['past_adv'] / divisor
            buckets = equal_volume_buckets(eligible.volume.to_numpy(), eligible.buy_ratio.to_numpy(),
                eligible.datetime.to_numpy(), size)
        count = len(buckets)
        audits.append(dict(**row, divisor=divisor, bucket_size=size,
            classified_volume=float(eligible.volume.sum()), completed_buckets=count,
            completed_volume=float(count * size) if count else 0.0,
            unfinished_volume=float(eligible.volume.sum() - count * size) if count else float(eligible.volume.sum()),
            warmup_volume_excluded=float(group.loc[group.buy_ratio.isna(), 'volume'].sum())))
        if count:
            buckets['segment'] = row['segment']
            buckets['source_contract'] = row['source_contract']
            tables.append(buckets)
    empty = pd.DataFrame(columns=['completed_at', 'bucket_number', 'bucket_size', 'buy_volume', 'sell_volume', 'imbalance', 'segment', 'source_contract'])
    return pd.concat(tables, ignore_index=True) if tables else empty, pd.DataFrame(audits)


def daily_features(prepared: pd.DataFrame, buckets: pd.DataFrame,
                   bucket_window: int, stats_window: int = 60, stats_minimum: int = 20,
                   slope_window: int = 5) -> pd.DataFrame:
    daily = prepared.groupby('date', sort=True).agg(source_contract=('source_contract', 'first'),
        segment=('segment', 'first')).reset_index()
    bucket = buckets.copy()
    if bucket.empty:
        daily['vpin'] = np.nan
        daily['completed_buckets'] = 0
    else:
        bucket['vpin'] = bucket.groupby('segment', sort=False).imbalance.transform(
            lambda s: s.rolling(bucket_window, min_periods=bucket_window).mean())
        bucket['date'] = bucket.completed_at.dt.normalize()
        ending = bucket.groupby('date', sort=True).tail(1).set_index('date')
        daily['vpin'] = daily.date.map(ending.vpin)
        daily['completed_buckets'] = daily.date.map(bucket.groupby('date').size()).fillna(0).astype(int)
    daily['percentile'] = np.nan
    daily['slope'] = np.nan
    x = np.arange(slope_window, dtype=float)
    x -= x.mean()
    for _, group in daily.groupby('segment', sort=False):
        history = deque(maxlen=stats_window)
        slopes = deque(maxlen=slope_window)
        for idx, value in zip(group.index, group.vpin):
            valid = np.asarray([v for v in history if np.isfinite(v)], dtype=float)
            if np.isfinite(value) and len(valid) >= stats_minimum:
                daily.loc[idx, 'percentile'] = float(np.mean(valid <= value))
            slopes.append(value)
            if len(slopes) == slope_window and np.isfinite(slopes).all():
                daily.loc[idx, 'slope'] = float(np.dot(x, np.asarray(slopes)) / np.dot(x, x))
            # Append after ranking, so no current observation enters its own reference CDF.
            history.append(value)
    return daily


def execution_days(df: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """Create independent daily entry/exit proxies, with no cross-contract price returns."""
    rows = []
    previous = pd.Series(calendar, index=calendar).shift(1)
    for date, group in df.groupby('date', sort=True):
        morning = group.iloc[1:].loc[group.iloc[1:].datetime.dt.hour < 12]
        liquid = morning.loc[morning.volume.gt(0)]
        final = group.iloc[-1]
        row = dict(date=date, previous_open_date=previous.loc[date],
            source_contract=group.source_contract.iloc[0], exit_time=final.datetime,
            exit_price=float(final.close), exit_volume=float(final.volume),
            entry_time=pd.NaT, entry_price=np.nan, entry_volume=0.0,
            entry_delayed_bars=0, fill_status='no_morning_entry', gross_return=0.0)
        if not liquid.empty:
            entry = liquid.iloc[0]
            row.update(entry_time=entry.datetime, entry_price=float(entry.open),
                entry_volume=float(entry.volume), entry_delayed_bars=int(group.index.get_loc(entry.name) - 1))
            if final.volume <= 0:
                row.update(fill_status='unverified_exit', gross_return=np.nan)
            else:
                row.update(fill_status='proxy_filled', gross_return=float(final.close / entry.open - 1.0))
        rows.append(row)
    return pd.DataFrame(rows)


def make_ledger(feature: pd.DataFrame, execution: pd.DataFrame, threshold: float) -> pd.DataFrame:
    signal = feature.copy().set_index('date')
    signal['available'] = signal[['vpin', 'percentile', 'slope']].notna().all(axis=1)
    signal['signal'] = (signal.available & ~((signal.percentile >= threshold) & (signal.slope > 0))).astype(float)
    result = execution.copy()
    known = signal.reindex(pd.DatetimeIndex(result.previous_open_date))
    result['signal_date'] = known.index.to_numpy()
    result['signal_contract'] = known.source_contract.to_numpy()
    result['signal_available'] = known.available.fillna(False).to_numpy(dtype=bool)
    result['signal_value'] = known.signal.fillna(0.0).to_numpy(float)
    same_contract = result.signal_contract.eq(result.source_contract)
    result['position'] = np.where(same_contract & result.entry_price.notna(), result.signal_value, 0.0)
    result['benchmark_position'] = result.entry_price.notna().astype(float)
    result['roll_day'] = result.source_contract.ne(result.source_contract.shift())
    result['strategy_turnover'] = result.position * 2.0
    result['benchmark_turnover'] = result.benchmark_position * 2.0
    result['strategy_gross'] = result.position * result.gross_return
    result['benchmark_gross'] = result.benchmark_position * result.gross_return
    return result


def metrics(ledger: pd.DataFrame, cost_bp: int, kind: str) -> dict:
    returns = ledger[f'{kind}_gross'] - cost_bp * 1e-4 * ledger[f'{kind}_turnover']
    if returns.isna().any():
        raise ValueError('Unverified exit: cannot report complete strategy performance')
    nav = (1.0 + returns).cumprod()
    drawdown = nav / np.maximum.accumulate(np.r_[1.0, nav.to_numpy()])[1:] - 1.0
    std = float(returns.std(ddof=0))
    mean = float(returns.mean())
    return dict(cost_bp=cost_bp, strategy=kind, days=len(returns),
        cumulative_return=float(nav.iloc[-1] - 1.0), annualized_return=float(nav.iloc[-1] ** (252 / len(nav)) - 1.0),
        annualized_volatility=std * np.sqrt(252), sharpe=mean / std * np.sqrt(252) if std > 0 else 0.0,
        max_drawdown=float(-drawdown.min()), mean_exposure=float(ledger[f'{kind}_position' if kind=='benchmark' else 'position'].mean()),
        executed_days=int(ledger[f'{kind}_turnover'].gt(0).sum()))


def phase(date: pd.Series) -> pd.Series:
    return pd.Series(np.select([date < pd.Timestamp('2023-01-01'), date < pd.Timestamp('2024-01-01'),
        date < pd.Timestamp('2025-01-01')], ['history', 'training', 'validation'], default='holdout'), index=date.index)


def run_research(data_dir: Path, output_dir: Path = Path('results/minute_vpin'),
                 products: tuple[str, ...] = PRODUCTS) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    private = Path('data/processed/minute_vpin')
    private.mkdir(parents=True, exist_ok=True)
    calendar_raw = pd.read_csv(data_dir / 'metadata/trading_calendar.csv', dtype={'cal_date': str})
    calendar = pd.DatetimeIndex(pd.to_datetime(calendar_raw.loc[calendar_raw.is_open.eq(1), 'cal_date'], format='%Y%m%d').sort_values().unique())
    features, executions, quality, audits = {}, {}, [], []
    for name in products:
        df, detail = read_input(data_dir / f'research/{name}_1min.parquet', calendar)
        prepared, calibration = prepare_segments(df, calendar)
        executions[name] = execution_days(prepared, calendar)
        failed = executions[name].loc[executions[name].fill_status.eq('unverified_exit')]
        if not failed.empty:
            failed.to_csv(output_dir / f'{name}_execution_failures.csv', index=False)
            if failed.date.ge(pd.Timestamp('2023-01-01')).any():
                raise ValueError(f'{name}: training/validation/holdout exit unverified; see execution_failures')
        detail['product'] = name
        detail['rolls_or_gaps'] = int(calibration.segment.nunique())
        detail['delayed_entries'] = int(executions[name].entry_delayed_bars.gt(0).sum())
        detail['no_morning_entry'] = int(executions[name].fill_status.eq('no_morning_entry').sum())
        detail['unverified_exit'] = len(failed)
        detail['zero_volume_final_bars'] = int(executions[name].exit_volume.eq(0).sum())
        quality.append(detail)
        for divisor in (25, 50):
            buckets, audit = build_buckets(prepared, calibration, divisor)
            audit['product'] = name
            audits.append(audit)
            buckets.to_parquet(private / f'{name}_buckets_{divisor}.parquet', index=False)
            for window in (20, 50):
                features[(name, divisor, window)] = daily_features(prepared, buckets, window)
        print(f'{name}: {len(df):,} complete minute rows; {len(executions[name])} days', flush=True)
    candidates, ledgers = [], {}
    for divisor, window, threshold in GRID:
        scores = []
        for name in products:
            ledger = make_ledger(features[(name, divisor, window)], executions[name], threshold)
            ledger['product'] = name
            ledger['phase'] = phase(ledger.date)
            ledgers[(name, divisor, window, threshold)] = ledger
            train = ledger.loc[ledger.phase.eq('training')]
            if train.empty:
                raise ValueError(f'{name}: no training observations')
            score = metrics(train, 1, 'strategy')
            scores.append(score['sharpe'])
        candidates.append(dict(bucket_divisor=divisor, bucket_window=window, threshold=threshold,
            training_mean_product_sharpe=float(np.mean(scores)), **{f'{n}_training_sharpe': s for n, s in zip(products, scores)}))
    selection = pd.DataFrame(candidates).sort_values(['training_mean_product_sharpe', 'bucket_divisor', 'bucket_window', 'threshold'],
        ascending=[False, True, True, True]).reset_index(drop=True)
    selected = selection.iloc[0]
    chosen = (int(selected.bucket_divisor), int(selected.bucket_window), float(selected.threshold))
    selection['selected'] = np.arange(len(selection)) == 0
    selection.to_csv(output_dir / 'training_selection.csv', index=False)
    all_ledgers, all_features, summary, blocked = [], [], [], []
    for name in products:
        ledger = ledgers[(name, *chosen)].copy()
        all_ledgers.append(ledger)
        feature = features[(name, chosen[0], chosen[1])].copy()
        feature['product'] = name
        all_features.append(feature)
        for period in ('history', 'training', 'validation', 'holdout', 'all'):
            part = ledger if period == 'all' else ledger.loc[ledger.phase.eq(period)]
            if part.empty:
                continue
            if part.gross_return.isna().any():
                blocked.append(dict(product=name, phase=period, unverified_exit=int(part.gross_return.isna().sum()),
                    reason='Historical entry observed but zero-volume final bar; no verified exit or complete performance.'))
                continue
            for cost in COSTS_BP:
                for kind in ('strategy', 'benchmark'):
                    summary.append(dict(product=name, phase=period, start=str(part.date.iloc[0].date()), end=str(part.date.iloc[-1].date()), **metrics(part, cost, kind)))
    execution = pd.concat(all_ledgers, ignore_index=True)
    execution.to_csv(output_dir / 'execution_ledger.csv', index=False)
    pd.concat(all_features, ignore_index=True).to_csv(output_dir / 'daily_features.csv', index=False)
    pd.DataFrame(blocked, columns=['product', 'phase', 'unverified_exit', 'reason']).to_csv(output_dir / 'metrics_blocked.csv', index=False)
    statistics = pd.DataFrame(summary)
    statistics.to_csv(output_dir / 'summary.csv', index=False)
    pd.DataFrame(quality).to_csv(output_dir / 'data_quality.csv', index=False)
    pd.concat(audits, ignore_index=True).to_csv(output_dir / 'bucket_audit.csv', index=False)
    receipt = dict(status='complete_with_historical_execution_limits' if blocked else 'complete', historical_metrics_blocked=blocked, generated_at=pd.Timestamp.now(tz='Asia/Shanghai').isoformat(),
        source='tushare', data_dir=str(data_dir.resolve()), products=list(products),
        selected=dict(bucket_divisor=chosen[0], bucket_window=chosen[1], threshold=chosen[2]),
        training='2023-01-01 to 2023-12-31 (TL only since actual listing)', validation='2024-01-01 to 2024-12-31',
        holdout='2025-01-01 onward; no retuning', costs_bp=list(COSTS_BP),
        execution='Previous complete exchange-open day signal; next day second bar open proxy or next positive-volume morning bar; final bar close proxy; flat overnight.',
        evaluation='Price percentage returns on equal notional; no leverage/margin return; OHLC proxy fills without bid/ask.',
        quality=quality)
    (output_dir / 'provenance.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    write_report(output_dir, receipt, statistics)
    plot_nav(output_dir, execution)
    print(json.dumps(dict(selected=receipt['selected'], quality=quality), ensure_ascii=False), flush=True)
    return receipt


def write_report(output_dir: Path, receipt: dict, statistics: pd.DataFrame) -> None:
    held = statistics.loc[statistics.phase.eq('holdout') & statistics.cost_bp.eq(1)]
    failed = sum(q['unverified_exit'] for q in receipt['quality'])
    execution_note = (f'早期 TS 有 {failed} 个已入场日无法从零成交末根验证平仓；另有无上午成交入口的日子未入场。这些日的源数据、桶、特征和失败账本保留，TS 早期历史及全历史完整绩效不披露。见 [受限绩效范围](metrics_blocked.csv) 和 本地失败平仓账本 `TS_execution_failures.csv`（不随 Git 发布）。四品种 2023 年起均没有平仓验证失败。' if failed else '没有观察到入场后末根零成交的平仓验证失败。')
    lines = ['# 四品种一分钟 VPIN 研究', '',
        '**单边 1 bp 成本的固定检验段，四品种策略均亏损。**相同日内口径下相较每日全多基准亏损较少，但降低暴露和交易次数本身会减少成本，不能据此证明 VPIN 具有方向预测能力或可以实盘盈利。', '',
        '本次修复了旧实现将固定分钟根误当固定成交量桶的问题。源数据扩展和正确的因果计算不保证策略收益提高。', '',
        '只使用 Tushare 真实月合约；完整日由历史交易时段确定，缺分钟和缺开市日不插值。各品种有效范围见下表。', '',
        execution_note, '',
        '| 品种 | 完整分钟根 | 完整交易日 | 首根 | 末根 | 不完整观察日 | 整日缺口 |',
        '|---|---:|---:|---|---|---:|---:|']
    for q in receipt['quality']:
        lines.append(f"| {q['product']} | {q['complete_rows']:,} | {q['complete_days']:,} | {q['first_datetime']} | {q['last_datetime']} | {q['incomplete_days']} | {q['missing_open_days']} |")
    lines += ['', '执行前一开市日收盘后信号，下一日第二根开盘代理入场、末根收盘代理平仓；第二根零量时等待后续上午有量根。策略与基准均每日进出同一合约，没有隔夜或跨合约价差收益。换月和缺口重置成交量桶/价格尺度，换月日不沿用旧合约信号。', '',
        '分钟 OHLC 和成交量只能支持理想成交研究，没有真实 bid/ask、撮合顺序或市场冲击验证。零量根不会被当作成交。所有价格百分比均为名义本金收益，未使用保证金杠杆。', '',
        f"预先固定 8 格在 2023 训练段按四品种等权净收益夏普选择：**ADV/{receipt['selected']['bucket_divisor']}、{receipt['selected']['bucket_window']} 桶窗口、{receipt['selected']['threshold']} 分位阈值**。TL 训练只有上市后月份。2024 只验证，2025 年起固定检验，不重新选参数。详见 [研究协议](protocol.md) 和 [选择表](training_selection.csv)。", '',
        '下表是固定检验段单边 1 bp 成本结果；基准同样扣每日两次成交成本。', '',
        '| 品种 | 策略 | 天数 | 累计收益 | 年化收益 | 夏普 | 最大回撤 | 平均仓位 |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for r in held.to_dict('records'):
        lines.append(f"| {r['product']} | {r['strategy']} | {r['days']} | {r['cumulative_return']:.2%} | {r['annualized_return']:.2%} | {r['sharpe']:.3f} | {r['max_drawdown']:.2%} | {r['mean_exposure']:.2%} |")
    lines += ['', '成本敏感性（固定检验段策略累计收益，单边成本）：', '',
        '| 品种 | 0 bp | 1 bp | 3 bp |', '|---|---:|---:|---:|']
    sensitivity = statistics.loc[statistics.phase.eq('holdout') & statistics.strategy.eq('strategy')]
    for name, group in sensitivity.groupby('product', sort=False):
        rates = group.set_index('cost_bp').cumulative_return
        lines.append(f'| {name} | {rates.loc[0]:.2%} | {rates.loc[1]:.2%} | {rates.loc[3]:.2%} |')
    lines += ['', '![固定检验日内净值](holdout_nav.png)', '',
        '更早历史仍保留用于在线热身和描述。由于已使用 2023 年挑选参数，全历史汇总及 2023 年前段不能称为新的独立样本外结果。各段与单边 0/1/3 bp 敏感性见 [完整结果](summary.csv)。', '',
        'BVC 是由价格变化估计成交方向；分类尺度只用过去 200 根，至少 50 根过去变化热身。ADV 只用过去 20 个完整开市日，在每个连续合约段开始时锁定。部分分钟按固定比例跨桶分配，未满桶不发布 VPIN。日分位参照排除当前值。明细见 [桶守恒审计](bucket_audit.csv)、[日特征](daily_features.csv)、本地执行账本 `execution_ledger.csv`（不随 Git 发布）、[数据质量](data_quality.csv)。', '',
        '公共源跨频核验保留了分钟与日线差异：TF1312 在 2013-11-19 的分钟收盘 90.100 与日线 90.940 不同，持仓相差 1197；没有使用日线修补分钟源。这发生于 2023 年训练之前，相关全历史描述须结合该质量问题解释。分钟成交量与日线成交量也可能因历史计数及竞价口径不同而有差异，本文成交量桶只按 Tushare 分钟 volume 计算，未声称两种频率的成交量完全相等。', '',
        'VPIN 的经济解释和预测能力存在学术争议，本结果不能把 BVC 估计值解释为真实主动买卖量或知情交易概率，也不构成可成交性证明。', '',
        '复现：', '', '```powershell', 'python vpin_timing.py --data-dir "path/to/cgb-market-data"',
        'python scripts/verify_minute_vpin.py --data-dir "path/to/cgb-market-data"', '```', '',
        '[VPIN 原始理论说明](https://www.quantresearch.org/VPIN.pdf)；[Andersen、Bondarenko 的分类准确性研究](https://repec.econ.au.dk/repec/creates/rp/13/rp13_43.pdf)。', '']
    lines += ['执行账本及全部分钟/桶数据保留在本地；按上方命令重新获取自己的行情数据并运行研究即可生成。', '']
    (output_dir / 'report.md').write_text('\n'.join(lines), encoding='utf-8')


def plot_nav(output_dir: Path, ledger: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    figure, axes = plt.subplots(2, 2, figsize=(13, 8), sharex=True)
    for axis, (name, group) in zip(axes.flat, ledger.groupby('product', sort=False)):
        group = group.loc[group.phase.eq('holdout')]
        for kind, label in [('strategy', 'VPIN'), ('benchmark', 'Daily intraday long')]:
            returns = group[f'{kind}_gross'] - 1e-4 * group[f'{kind}_turnover']
            axis.plot(group.date, (1.0 + returns).cumprod(), label=label)
        axis.set_title(f'{name}: holdout, 1 bp per side')
        axis.grid(alpha=0.25)
        locator = mdates.MonthLocator(interval=4)
        axis.xaxis.set_major_locator(locator)
        axis.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        axis.legend()
    figure.tight_layout()
    figure.savefig(output_dir / 'holdout_nav.png', dpi=180)
    plt.close(figure)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, default=Path('results/minute_vpin'))
    args = parser.parse_args()
    run_research(args.data_dir, args.output_dir)
