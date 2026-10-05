"""Independent source-price, timing, fixed-volume and cashflow audit."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def verify(data_dir: Path, output_dir: Path) -> dict:
    receipt=json.loads((output_dir/'provenance.json').read_text(encoding='utf-8'))
    ledger=pd.read_csv(output_dir/'execution_ledger.csv',parse_dates=['date','previous_open_date','signal_date','entry_time','exit_time'])
    feature=pd.read_csv(output_dir/'daily_features.csv',parse_dates=['date'])
    audit=pd.read_csv(output_dir/'bucket_audit.csv',parse_dates=['calibration_date'])
    summary=pd.read_csv(output_dir/'summary.csv')
    selection=pd.read_csv(output_dir/'training_selection.csv')
    calendar_raw=pd.read_csv(data_dir/'metadata/trading_calendar.csv',dtype={'cal_date':str})
    calendar=pd.DatetimeIndex(pd.to_datetime(calendar_raw.loc[calendar_raw.is_open.eq(1),'cal_date'],format='%Y%m%d').sort_values().unique())
    previous=pd.Series(calendar,index=calendar).shift(1)
    selected=receipt['selected']
    checks=[]
    row_count=0
    for name in receipt['products']:
        raw=pd.read_parquet(data_dir/f'research/{name}_1min.parquet')
        raw['date']=pd.to_datetime(raw.datetime).dt.normalize()
        assert raw.source.eq('tushare').all(),f'{name}: source'
        complete=raw.groupby('date').session_complete.all()
        raw=raw.loc[raw.date.isin(complete.index[complete])]
        daily_volume=raw.groupby('date').volume.sum().reindex(calendar)
        mapping=pd.read_csv(data_dir/f'metadata/effective_mapping_{name}.csv',parse_dates=['trade_date','mapping_known_date'])
        mapping=mapping.set_index('trade_date')
        part=ledger.loc[ledger['product'].eq(name)].copy()
        assert not part.date.duplicated().any()
        assert np.array_equal(part.previous_open_date.to_numpy(),previous.reindex(part.date).to_numpy())
        assert (part.signal_date<part.date).all()
        assert not part.loc[part.date.ge(pd.Timestamp('2023-01-01')), 'fill_status'].eq('unverified_exit').any()
        bydate={date:g for date,g in raw.groupby('date')}
        for row in part.itertuples(index=False):
            group=bydate[row.date]
            assert row.source_contract==group.source_contract.iloc[0]==mapping.loc[row.date,'source_contract']
            assert mapping.loc[row.date,'mapping_known_date']<row.date
            if row.fill_status=='proxy_filled':
                chosen=group.iloc[1:].loc[(group.iloc[1:].datetime.dt.hour<12)&group.iloc[1:].volume.gt(0)].iloc[0]
                assert row.entry_time==chosen.datetime
                assert row.entry_price==chosen.open and row.entry_volume>0
                final=group.iloc[-1]
                assert row.exit_time==final.datetime and row.exit_price==final.close and row.exit_volume>0
                assert np.isclose(row.gross_return,final.close/chosen.open-1,rtol=0,atol=1e-14)
            elif row.fill_status=='unverified_exit':
                assert row.date<pd.Timestamp('2023-01-01') and row.exit_volume==0 and pd.isna(row.gross_return)
                assert row.entry_volume>0 and row.benchmark_position==1
            else:
                assert row.position==0 and row.benchmark_position==0
            assert row.strategy_turnover==2*row.position
            assert row.benchmark_turnover==2*row.benchmark_position
            assert np.isclose(row.strategy_gross,row.position*row.gross_return,atol=1e-14,equal_nan=True)
            assert np.isclose(row.benchmark_gross,row.benchmark_position*row.gross_return,atol=1e-14,equal_nan=True)
        local_feature=feature.loc[feature['product'].eq(name)].set_index('date')
        for row in part.itertuples(index=False):
            if row.previous_open_date not in local_feature.index:
                assert row.position==0
                continue
            prior=local_feature.loc[row.previous_open_date]
            valid=np.isfinite([prior.vpin,prior.percentile,prior.slope]).all()
            desired=float(valid and not(prior.percentile>=selected['threshold'] and prior.slope>0))
            same=prior.source_contract==row.source_contract
            expected=desired if same and row.fill_status!='no_morning_entry' else 0.
            assert row.position==expected
        product_audit=audit.loc[audit['product'].eq(name)&audit.divisor.eq(selected['bucket_divisor'])]
        buckets=pd.read_parquet(Path('data/processed/minute_vpin')/f'{name}_buckets_{selected["bucket_divisor"]}.parquet')
        assert np.allclose(buckets.buy_volume+buckets.sell_volume,buckets.bucket_size,atol=1e-7)
        assert np.allclose(buckets.imbalance,abs(buckets.buy_volume-buckets.sell_volume)/buckets.bucket_size,atol=1e-9)
        for row in product_audit.itertuples(index=False):
            if pd.isna(row.calibration_date):
                continue
            ordinal=calendar.get_loc(row.calibration_date)
            prior_volume=daily_volume.iloc[ordinal-20:ordinal]
            assert len(prior_volume)==20 and prior_volume.notna().all()
            assert np.isclose(row.past_adv,prior_volume.mean(),atol=1e-7)
            assert np.isclose(row.bucket_size,row.past_adv/row.divisor,atol=1e-7)
            assert np.isclose(row.classified_volume,row.completed_volume+row.unfinished_volume,atol=1e-6)
            assert row.unfinished_volume>=-1e-6 and row.unfinished_volume<row.bucket_size+1e-6
            segment=buckets.loc[buckets.segment.eq(row.segment)]
            assert len(segment)==row.completed_buckets
            assert (segment.completed_at.dt.normalize()>=row.calibration_date).all()
            assert segment.source_contract.eq(row.source_contract).all()
        # Reconstruct selected VPIN, its daily historical CDF and slope without calling research functions.
        vpin=buckets.groupby('segment').imbalance.transform(lambda s:s.rolling(selected['bucket_window']).sum()/selected['bucket_window'])
        bucket_dates=buckets.completed_at.dt.normalize()
        endpoints=pd.DataFrame({'date':bucket_dates,'vpin':vpin}).groupby('date').tail(1).set_index('date').vpin
        reconstructed=local_feature.index.map(endpoints)
        assert np.allclose(local_feature.vpin,reconstructed,equal_nan=True,atol=1e-10)
        for _,group in local_feature.groupby('segment',sort=False):
            values=group.vpin.to_numpy(float)
            for i,(date,r) in enumerate(group.iterrows()):
                past=values[max(0,i-60):i]
                past=past[np.isfinite(past)]
                rank=np.mean(past<=values[i]) if len(past)>=20 and np.isfinite(values[i]) else np.nan
                assert np.isclose(r.percentile,rank,equal_nan=True,atol=1e-10)
                current=values[max(0,i-4):i+1]
                slope=np.polyfit(np.arange(5),current,1)[0] if len(current)==5 and np.isfinite(current).all() else np.nan
                assert np.isclose(r.slope,slope,equal_nan=True,atol=1e-10)
        for metric in summary.loc[summary['product'].eq(name)].itertuples(index=False):
            section=part if metric.phase=='all' else part.loc[part.phase.eq(metric.phase)]
            returns=section[f'{metric.strategy}_gross']-metric.cost_bp*1e-4*section[f'{metric.strategy}_turnover']
            expected=np.prod(1+returns)-1
            assert np.isclose(metric.cumulative_return,expected,atol=1e-12)
        row_count+=len(part)
        checks.append({'product':name,'daily_cashflows_verified':len(part),'complete_minutes':len(raw),
            'selected_buckets':len(buckets),'mapping_dates_verified':len(part),'unverified_historical_exits':int(part.fill_status.eq('unverified_exit').sum())})
    assert len(selection)==8 and selection.selected.sum()==1
    winner=selection.loc[selection.selected].iloc[0]
    assert winner.training_mean_product_sharpe==selection.training_mean_product_sharpe.max()
    assert (int(winner.bucket_divisor),int(winner.bucket_window),float(winner.threshold))==(selected['bucket_divisor'],selected['bucket_window'],selected['threshold'])
    training=summary.loc[summary.phase.eq('training')&summary.cost_bp.eq(1)&summary.strategy.eq('strategy')]
    assert np.isclose(training.sharpe.mean(),winner.training_mean_product_sharpe,atol=1e-12)
    result=dict(status='passed',verified_at=pd.Timestamp.now(tz='Asia/Shanghai').isoformat(),
        daily_cashflows=row_count,selected=selected,checks=checks,
        scope='Independent source prices, prior-day mapping/signal timing, ADV calibration, equal-volume bucket accounting, historical ranks, slope and net-return compounding; proxy fill assumptions remain unverified by tick/bid-ask data.')
    (output_dir/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,default=Path('results/minute_vpin'))
    args=parser.parse_args()
    verify(args.data_dir,args.output_dir)
