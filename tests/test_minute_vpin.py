from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from minute_vpin import (equal_volume_buckets, prepare_segments, build_buckets,
    daily_features, execution_days, make_ledger, metrics, read_input)


def frame(days=32, minutes=60):
    calendar=pd.bdate_range('2023-01-02',periods=days)
    records=[]
    for i,date in enumerate(calendar):
        for k in range(minutes):
            close=100 + i*.01 + k*.0001 * (-1 if k%3 else 1)
            records.append(dict(datetime=date+pd.Timedelta(hours=9,minutes=31+k), date=date,
                open=close-.001, high=close+.01, low=close-.01, close=close,
                volume=100., source_contract='T2306.CFX', source='tushare', session_complete=True))
    return pd.DataFrame(records),calendar


def test_fractional_bar_crosses_bucket_and_unfinished_not_published():
    times=pd.date_range('2023-01-02 09:31',periods=2,freq='min').to_numpy()
    actual=equal_volume_buckets(np.array([70.,180.]),np.array([1.,0.]),times,100)
    assert actual.buy_volume.tolist()==pytest.approx([70.,0.])
    assert actual.sell_volume.tolist()==pytest.approx([30.,100.])
    assert actual.imbalance.tolist()==pytest.approx([.4,1.])
    assert actual.completed_at.tolist()==[pd.Timestamp(times[1])]*2
    assert len(actual)==2


def test_multiple_buckets_same_bar_and_zero_volume_preserve_mass():
    times=pd.date_range('2023-01-02 09:31',periods=3,freq='min').to_numpy()
    actual=equal_volume_buckets(np.array([0.,250.,0.]),np.array([1.,.25,0.]),times,100)
    assert actual.buy_volume.tolist()==pytest.approx([25.,25.])
    assert (actual.buy_volume+actual.sell_volume).tolist()==pytest.approx([100.,100.])
    assert (actual.completed_at==pd.Timestamp(times[1])).all()
    with pytest.raises(ValueError,match='invalid'):
        equal_volume_buckets(np.array([-1.]),np.array([.5]),times[:1],100)


def test_volume_calibration_and_bvc_do_not_see_future_rows():
    source,calendar=frame()
    early,_=prepare_segments(source.iloc[:29*60],calendar)
    changed=source.copy()
    changed.loc[changed.date>=calendar[29],'volume']=1e9
    changed.loc[changed.date>=calendar[29],'close']=999
    late,_=prepare_segments(changed,calendar)
    pd.testing.assert_series_equal(early.buy_ratio,late.buy_ratio.iloc[:len(early)])
    _,calibration=prepare_segments(source,calendar)
    assert calibration.iloc[0].calibration_date==str(calendar[20].date())
    assert calibration.iloc[0].past_adv==6000
    assert source.iloc[:20*60].volume.sum()>0
    assert early.buy_ratio.iloc[:20*60+50].isna().all()


def test_reentered_contract_and_missing_open_day_reset_state():
    source,calendar=frame()
    source.loc[source.date==calendar[25],'source_contract']='T2309.CFX'
    source=source.loc[source.date!=calendar[28]].reset_index(drop=True)
    prepared,calibration=prepare_segments(source,calendar,adv_window=2,sigma_minimum=2)
    assert len(calibration)==4  # A, B, A, gap + A
    for _,g in prepared.groupby('segment'):
        active=g.loc[g.date>=pd.Timestamp(calibration.loc[calibration.segment.eq(g.segment.iloc[0]),'calibration_date'].iloc[0])]
        assert active.buy_ratio.iloc[:2].isna().all()


def test_bucket_audit_volume_identity():
    source,calendar=frame()
    prepared,calibration=prepare_segments(source,calendar)
    buckets,audit=build_buckets(prepared,calibration,25)
    assert len(buckets)>0
    assert np.allclose(audit.classified_volume,audit.completed_volume+audit.unfinished_volume)
    assert audit.unfinished_volume.iloc[0]<audit.bucket_size.iloc[0]
    assert np.allclose(buckets.buy_volume+buckets.sell_volume,buckets.bucket_size)


def test_daily_rank_excludes_current_and_uncompleted_buckets():
    source,calendar=frame(days=8,minutes=2)
    source['segment']=1
    buckets=pd.DataFrame(dict(completed_at=calendar+pd.Timedelta(hours=15),
        imbalance=np.arange(8)/10, segment=1))
    actual=daily_features(source,buckets,2,stats_window=4,stats_minimum=2,slope_window=2)
    assert pd.isna(actual.percentile.iloc[2])
    assert actual.percentile.iloc[3]==1
    before=actual.iloc[:6].copy()
    buckets.loc[7,'imbalance']=0
    after=daily_features(source,buckets,2,stats_window=4,stats_minimum=2,slope_window=2)
    pd.testing.assert_frame_equal(before,after.iloc[:6])


def test_entry_delay_and_roll_do_not_fabricate_execution():
    source,calendar=frame(days=3,minutes=4)
    source.loc[(source.date==calendar[1]) & (source.datetime.dt.minute==32),'volume']=0
    source.loc[source.date==calendar[2],'source_contract']='T2309.CFX'
    execution=execution_days(source,calendar)
    assert execution.entry_delayed_bars.tolist()==[0,1,0]
    features=pd.DataFrame(dict(date=calendar,source_contract=['T2306.CFX','T2306.CFX','T2309.CFX'],
        vpin=.1,percentile=.1,slope=.1))
    ledger=make_ledger(features,execution,.8)
    assert ledger.position.tolist()==[0.,1.,0.]
    assert (ledger.signal_date.iloc[1:]<ledger.date.iloc[1:]).all()
    assert ledger.gross_return.iloc[2]==pytest.approx(source.loc[source.date==calendar[2]].close.iloc[-1]/source.loc[source.date==calendar[2]].open.iloc[1]-1)
    strategy=metrics(ledger,1,'strategy')
    benchmark=metrics(ledger,1,'benchmark')
    assert strategy['executed_days']==1
    assert benchmark['executed_days']==3


def test_zero_exit_is_unverified_not_zero_return():
    source,calendar=frame(days=2,minutes=4)
    source.loc[source.index[-1],'volume']=0
    execution=execution_days(source,calendar)
    assert execution.fill_status.iloc[-1]=='unverified_exit'
    assert pd.isna(execution.gross_return.iloc[-1])
    feature=pd.DataFrame(dict(date=calendar,source_contract='T2306.CFX',vpin=.1,percentile=.1,slope=.1))
    with pytest.raises(ValueError,match='Unverified exit'):
        metrics(make_ledger(feature,execution,.8),1,'strategy')


def test_source_and_incomplete_session_gates(tmp_path):
    source,calendar=frame(days=3,minutes=4)
    source.loc[source.date==calendar[1],'session_complete']=False
    path=tmp_path/'T.parquet'
    source.to_parquet(path,index=False)
    actual,quality=read_input(path,calendar)
    assert len(actual)==8
    assert quality['incomplete_days']==1
    source.loc[0,'source']='akshare'
    source.to_parquet(path,index=False)
    with pytest.raises(ValueError,match='Tushare only'):
        read_input(path,calendar)
