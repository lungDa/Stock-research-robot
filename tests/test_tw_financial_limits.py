import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.db import get,put
from jobs import refresh_tw_financials as job
from jobs.tw_financial_summary import render_summary
from tests.test_mopsfin import seed_metadata,payload,CATALOG


def clock(monkeypatch):
    ticks=[0.0]
    monkeypatch.setattr(job,'time',SimpleNamespace(monotonic=lambda:ticks[0],time=time.time))
    return ticks


@pytest.mark.parametrize('cold',[False,True])
def test_preparation_exhausts_budget_without_request(monkeypatch,cold):
    if not cold:seed_metadata()
    ticks=clock(monkeypatch);read=job.get
    def slow_read(key,default=None):
        if key=='mopsfin:catalog':ticks[0]=25
        return read(key,default)
    monkeypatch.setattr(job,'get',slow_read)
    loader=Mock();monkeypatch.setattr(job,'request',loader)
    result=job.run(['6488.TWO'])
    assert result['state']=='limited' and result['stop_reason']=='time_limit'
    assert result['official_requests']==0 and result['scanned_tasks']==0
    assert result['preparation_seconds']==25 and result['elapsed_budget_seconds']==25
    assert result['failed_feeds']==0 and result['failures']==[]
    assert get('jobs:tw_financials')==result
    assert '已耗盡本批時間預算' in render_summary({'result':result})
    loader.assert_not_called()


@pytest.mark.parametrize('cold',[False,True])
def test_shared_source_quota_is_distinct_and_does_not_cool_feed(monkeypatch,cold):
    if not cold:seed_metadata()
    monkeypatch.setattr(job,'source_slot',Mock(return_value=False))
    loader=Mock();monkeypatch.setattr(job,'request',loader)
    result=job.run(['6488.TWO'])
    assert result['state']=='limited' and result['stop_reason']=='source_quota'
    assert result['official_requests']==result['failed_feeds']==0
    assert get('mopsfin:feed:6488.TWO:eps') is None
    assert '未取得官方來源的共用請求配額' in render_summary({'result':result})
    loader.assert_not_called()


def test_slow_slot_reservation_cannot_start_over_budget_request(monkeypatch):
    seed_metadata();ticks=clock(monkeypatch)
    def slot(*args):ticks[0]=25;return True
    monkeypatch.setattr(job,'source_slot',slot)
    loader=Mock();monkeypatch.setattr(job,'request',loader)
    result=job.run(['6488.TWO'])
    assert result['stop_reason']=='time_limit' and result['official_requests']==0
    assert get('mopsfin:cursor:6488.TWO')['value']==0
    assert get('mopsfin:feed:6488.TWO:eps') is None
    loader.assert_not_called()


def test_all_feed_cooldowns_are_counted_and_expiry_resumes(monkeypatch):
    seed_metadata()
    for field in ('eps','roe_pct'):
        put('mopsfin:feed:6488.TWO:'+field,{'next_attempt':time.time()+3600})
    loader=Mock();monkeypatch.setattr(job,'request',loader)
    result=job.run(['6488.TWO'])
    assert result['state']=='cooldown' and result['stop_reason']=='feed_cooldown'
    assert result['total_tasks']==result['scanned_tasks']==result['skipped_feed_cooldown']==2
    loader.assert_not_called()
    put('mopsfin:feed:6488.TWO:eps',{'next_attempt':0})
    loader.return_value=payload()
    result=job.run(['6488.TWO'])
    assert result['state']=='finished' and result['official_requests']==1
    assert result['updated_symbols']==1 and result['skipped_feed_cooldown']==1


def test_source_cooldown_differs_from_feed_cooldown(monkeypatch):
    put('annual:source:mopsfin',{'next_attempt':time.time()+3600,'reason':'private-token'})
    loader=Mock();monkeypatch.setattr(job,'request',loader)
    result=job.run(['6488.TWO'])
    assert result['stop_reason']=='source_cooldown' and result['scanned_tasks']==0
    assert 'private-token' not in str(result)
    assert get('jobs:tw_financials')==result
    loader.assert_not_called()


def test_metadata_request_limit_is_not_success_and_resumes(monkeypatch):
    monkeypatch.setattr(job,'request',Mock(return_value=CATALOG))
    result=job.run(['6488.TWO'],max_requests=1)
    assert result['state']=='limited' and result['stop_reason']=='request_limit'
    assert result['official_requests']==1 and result['updated_symbols']==0
    seed_metadata()
    monkeypatch.setattr(job,'request',Mock(side_effect=[payload(),payload('roe_pct')]))
    result=job.run(['6488.TWO'],max_requests=2)
    assert result['state']=='finished' and result['stop_reason']=='tasks_scanned'
    assert result['updated_symbols']==1


def test_busy_does_not_overwrite_active_worker_result(monkeypatch):
    from contextlib import contextmanager
    @contextmanager
    def busy(*args):yield False
    put('jobs:tw_financials',{'state':'active'})
    monkeypatch.setattr(job,'leased',busy)
    result=job.run(['6488.TWO'])
    assert result['stop_reason']=='worker_busy'
    assert get('jobs:tw_financials')=={'state':'active'}


def test_db_initialization_is_measured_outside_existing_budget(monkeypatch):
    seed_metadata();ticks=clock(monkeypatch)
    monkeypatch.setattr(job,'init_db',lambda:ticks.__setitem__(0,30))
    monkeypatch.setattr(job,'request',Mock(side_effect=[payload(),payload('roe_pct')]))
    result=job.run(['6488.TWO'])
    assert result['state']=='finished' and result['official_requests']==2
    assert result['db_init_seconds']==30 and result['elapsed_budget_seconds']==0


def test_parent_retains_zero_request_limit_and_marks_partial(monkeypatch):
    import json,subprocess
    from jobs import refresh_data
    seed_metadata()
    monkeypatch.setattr(job,'source_slot',Mock(return_value=False))
    result=job.run(['6488.TWO'])
    monkeypatch.setattr(refresh_data,'STEPS',['tw_financials'])
    monkeypatch.setattr(refresh_data.subprocess,'run',Mock(return_value=
        subprocess.CompletedProcess([],0,stdout=json.dumps(result)+'\n',stderr='')))
    summary=refresh_data.run()
    assert summary['state']=='partial'
    assert summary['steps']['tw_financials']['result']['stop_reason']=='source_quota'


def test_summary_rejects_injected_reasons_and_nonfinite_timings():
    result={'state':'limited','stop_reason':'time_limit','official_requests':0,
            'db_init_seconds':float('inf'),'preparation_seconds':'private-token',
            'elapsed_budget_seconds':float('nan'),'budget_seconds':True,
            'scanned_tasks':'private-token','total_tasks':2,'skipped_feed_cooldown':0}
    text=render_summary({'result':result})
    assert '未發出官方請求' in text and 'private-token' not in text
    assert '| 未提供 | 未提供 | 未提供 | 未提供 |' in text
    result['stop_reason']='private-token'
    assert 'private-token' not in render_summary({'result':result})
